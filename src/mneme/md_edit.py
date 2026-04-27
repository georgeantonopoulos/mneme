from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
MAX_FILE_BYTES = 200_000


def _normalise_rel(path: str | Path) -> str:
    rel = str(path or "").strip().replace("\\", "/")
    if not rel:
        raise ValueError("path is required")
    raw = Path(rel)
    if raw.is_absolute():
        raise ValueError("path must be vault-relative, not absolute")
    if any(part == ".." for part in raw.parts):
        raise ValueError("path must not contain '..'")
    if any(part.startswith(".") for part in raw.parts):
        raise ValueError("hidden paths are not allowed")
    if raw.suffix == "":
        rel += ".md"
    if Path(rel).suffix.lower() != ".md":
        raise ValueError("only Markdown .md notes are editable")
    return rel


def safe_resolve(vault_root: str | Path, path: str | Path) -> Path:
    root = Path(vault_root).expanduser().resolve()
    rel = _normalise_rel(path)
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes vault root") from exc
    return target


def rel_path(vault_root: str | Path, target: Path) -> str:
    return target.resolve().relative_to(Path(vault_root).expanduser().resolve()).as_posix()


def _check_size(target: Path, force: bool = False) -> None:
    if target.exists() and not force and target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"refusing to edit note over {MAX_FILE_BYTES} bytes without force")


def _read_text(target: Path, force: bool = False) -> str:
    _check_size(target, force=force)
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def _diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))


def atomic_write(target: Path, content: str, make_backup: bool = True) -> str | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if target.exists() and make_backup:
        stamp = time.strftime('%Y%m%d%H%M%S')
        backup_path = target.with_suffix(target.suffix + f".{stamp}.{os.getpid()}.{uuid.uuid4().hex[:8]}.bak")
        shutil.copy2(target, backup_path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        try:
            dir_fd = os.open(str(target.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp.exists():
            tmp.unlink()
    return str(backup_path) if backup_path else None


def _result(vault_root: Path, target: Path, operation: str, changed: bool, **extra):
    out = {"ok": True, "operation": operation, "path": rel_path(vault_root, target), "changed": changed}
    out.update(extra)
    return out


def read_note(vault_root: str | Path, path: str | Path, heading: str | None = None, force: bool = False):
    root = Path(vault_root).expanduser().resolve()
    target = safe_resolve(root, path)
    content = _read_text(target, force=force)
    if heading:
        span = _find_section(content, heading)
        content = content[span[0]:span[1]] if span else ""
    return _result(root, target, "read", False, content=content, line_count=content.count("\n") + (1 if content else 0))


def write_note(vault_root: str | Path, path: str | Path, content: str, mode: str = "append", dry_run: bool = False, force: bool = False):
    root = Path(vault_root).expanduser().resolve()
    target = safe_resolve(root, path)
    old = _read_text(target, force=force)
    if mode == "create":
        if target.exists() and not force:
            raise ValueError("note already exists; use overwrite or force")
        new = content
    elif mode == "overwrite":
        new = content
    elif mode == "append":
        separator = "" if not old or old.endswith("\n") or content.startswith("\n") else "\n"
        new = old + separator + content
    else:
        raise ValueError("mode must be create|append|overwrite")
    changed = new != old
    diff = _diff(old, new, rel_path(root, target)) if changed else ""
    backup_abs = None if dry_run or not changed else atomic_write(target, new)
    backup = rel_path(root, Path(backup_abs)) if backup_abs else None
    return _result(root, target, mode, changed, mode=mode, backup=backup, diff=diff if dry_run else "", bytes=len(new.encode("utf-8")))


def replace_exact(vault_root: str | Path, path: str | Path, find: str, replace: str, replace_all: bool = False, dry_run: bool = False, force: bool = False):
    if not find:
        raise ValueError("find must not be empty")
    root = Path(vault_root).expanduser().resolve()
    target = safe_resolve(root, path)
    old = _read_text(target, force=force)
    count = old.count(find)
    if count == 0:
        raise ValueError("find string not found")
    if count > 1 and not replace_all:
        raise ValueError("find string appears multiple times; use replace_all")
    new = old.replace(find, replace, -1 if replace_all else 1)
    diff = _diff(old, new, rel_path(root, target))
    backup_abs = None if dry_run else atomic_write(target, new)
    backup = rel_path(root, Path(backup_abs)) if backup_abs else None
    return _result(root, target, "replace", True, replacements=count if replace_all else 1, backup=backup, diff=diff if dry_run else "")


def _heading_text(raw: str) -> str:
    return raw.strip().rstrip("#").strip().lower()


def _find_section(content: str, heading: str):
    want = heading.strip().lower()
    matches = list(HEADING_RE.finditer(content))
    for i, match in enumerate(matches):
        level = len(match.group(1))
        if _heading_text(match.group(2)) != want:
            continue
        end = len(content)
        for next_match in matches[i + 1:]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        return (match.start(), end, match.end(), level)
    return None


def upsert_section(vault_root: str | Path, path: str | Path, heading: str, content: str, level: int = 2, dry_run: bool = False, force: bool = False):
    if not 1 <= level <= 6:
        raise ValueError("level must be 1..6")
    root = Path(vault_root).expanduser().resolve()
    target = safe_resolve(root, path)
    old = _read_text(target, force=force)
    body = content.rstrip("\n") + "\n"
    span = _find_section(old, heading)
    marker = f"{'#' * (span[3] if span else level)} {heading.strip()}"
    section = f"{marker}\n\n{body}"
    if span:
        start, end, _heading_end, _level = span
        suffix = "" if section.endswith("\n\n") or end >= len(old) else "\n"
        new = old[:start] + section + suffix + old[end:].lstrip("\n")
    else:
        sep = "" if not old else ("\n" if old.endswith("\n") else "\n\n")
        new = old + sep + section
    changed = new != old
    diff = _diff(old, new, rel_path(root, target)) if changed else ""
    backup_abs = None if dry_run or not changed else atomic_write(target, new)
    backup = rel_path(root, Path(backup_abs)) if backup_abs else None
    return _result(root, target, "upsert-section", changed, heading=heading, backup=backup, diff=diff if dry_run else "")


def _normalise_bullet(text: str) -> str:
    text = re.sub(r"^[-*]\s+", "", text.strip())
    return re.sub(r"\s+", " ", text).casefold()


def add_bullet(vault_root: str | Path, path: str | Path, heading: str, bullet: str, dry_run: bool = False, force: bool = False):
    clean = re.sub(r"^[-*]\s+", "", bullet.strip())
    if not clean:
        raise ValueError("bullet must not be empty")
    root = Path(vault_root).expanduser().resolve()
    target = safe_resolve(root, path)
    old = _read_text(target, force=force)
    span = _find_section(old, heading)
    if not span:
        return upsert_section(root, rel_path(root, target), heading, f"- {clean}\n", dry_run=dry_run, force=force)
    start, end, _heading_end, _level = span
    section = old[start:end]
    existing = {_normalise_bullet(line) for line in section.splitlines() if re.match(r"^\s*[-*]\s+", line)}
    if _normalise_bullet(clean) in existing:
        return _result(root, target, "add-bullet", False, heading=heading, deduped=True)
    new_section = section.rstrip("\n") + f"\n- {clean}\n"
    new = old[:start] + new_section + old[end:]
    diff = _diff(old, new, rel_path(root, target))
    backup_abs = None if dry_run else atomic_write(target, new)
    backup = rel_path(root, Path(backup_abs)) if backup_abs else None
    return _result(root, target, "add-bullet", True, heading=heading, backup=backup, diff=diff if dry_run else "")

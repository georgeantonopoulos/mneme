from __future__ import annotations

import datetime
import difflib
import fnmatch
import os
import re
import shutil
import subprocess
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


# ---------------------------------------------------------------------------
# New vault-level note operations: list, search, search-content, daily,
# move, delete, status
# ---------------------------------------------------------------------------

def _safe_resolve_folder(vault_root: str | Path, folder: str | Path | None) -> Path:
    """Resolve a folder path safely within the vault. Unlike safe_resolve,
    this does NOT append .md and allows directories."""
    root = Path(vault_root).expanduser().resolve()
    if folder and str(folder).strip() and str(folder).strip() != ".":
        raw = Path(str(folder).strip().replace("\\", "/"))
        if raw.is_absolute():
            raise ValueError("folder must be vault-relative, not absolute")
        if any(part == ".." for part in raw.parts):
            raise ValueError("folder must not contain '..'")
        if any(part.startswith(".") for part in raw.parts):
            raise ValueError("hidden paths are not allowed")
        target = (root / raw).resolve()
    else:
        target = root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("folder escapes vault root") from exc
    return target


def list_notes(vault_root: str | Path, path: str | Path | None = None, pattern: str | None = None) -> dict:
    """List .md files in a vault folder, optionally filtered by glob pattern."""
    root = Path(vault_root).expanduser().resolve()
    folder = _safe_resolve_folder(root, path)
    glob_pattern = pattern if pattern else "*.md"
    files = []
    for p in sorted(folder.rglob(glob_pattern)):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".md":
            continue
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            continue
        mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime, tz=datetime.timezone.utc)
        files.append({
            "name": p.name,
            "path": rel.as_posix(),
            "modified": mtime.isoformat(),
        })
    return {"files": files}


def search_notes(vault_root: str | Path, query: str, folder: str | Path | None = None) -> dict:
    """Search vault by filename (case-insensitive substring match)."""
    root = Path(vault_root).expanduser().resolve()
    search_root = _safe_resolve_folder(root, folder)
    lower_query = query.lower()
    matches = []
    for p in sorted(search_root.rglob("*.md")):
        if not p.is_file():
            continue
        if lower_query not in p.name.lower():
            continue
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            continue
        mtime = datetime.datetime.fromtimestamp(p.stat().st_mtime, tz=datetime.timezone.utc)
        matches.append({
            "name": p.name,
            "path": rel.as_posix(),
            "modified": mtime.isoformat(),
        })
    return {"matches": matches}


def search_content(vault_root: str | Path, query: str, folder: str | Path | None = None,
                   max_results: int = 10, context: int = 3) -> dict:
    """Full-text content search across vault .md files.

    Prefers ripgrep (rg) if available, falls back to grep.
    """
    root = Path(vault_root).expanduser().resolve()
    search_root = _safe_resolve_folder(root, folder)
    matches = []

    rg_available = shutil.which("rg") is not None

    if rg_available:
        cmd = [
            "rg", "--no-heading", "--line-number", "--with-filename",
            "--max-count", str(max_results),
            "--context", str(context),
            "--ignore-case",
            query,
            str(search_root),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                matches = _parse_rg_output(proc.stdout, root, context)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            rg_available = False

    if not rg_available:
        # Fallback to grep
        cmd = [
            "grep", "-r", "-n", "-i",
            "--context", str(context),
            query,
            str(search_root),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                matches = _parse_grep_output(proc.stdout, root, context)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Trim to max_results
    matches = matches[:max_results]
    return {"matches": matches}


def _parse_rg_output(output: str, root: Path, context_lines: int) -> list[dict]:
    """Parse ripgrep output with --context into structured match dicts."""
    matches = []
    current_file = None
    context_before = []
    pending_match = None

    for line in output.splitlines():
        if not line.strip():
            continue
        # Determine separator: rg uses ':' for match lines, '-' for context lines
        # Format: filepath:lineno:text  or  filepath-lineno-text
        # Try ':' separator first (match line)
        parts = line.split(":", 2)
        if len(parts) >= 3:
            filepath, lineno_str, text = parts[0], parts[1], parts[2]
            # Check it's actually a match (not a context line with ':' in text)
            # by verifying lineno is numeric
            try:
                lineno = int(lineno_str.strip())
            except ValueError:
                # Not a standard rg match line, skip
                continue
            if pending_match:
                matches.append(pending_match)
                pending_match = None
                context_before = []
            current_file = filepath
            rel_path_str = _try_rel_path(filepath, root)
            pending_match = {
                "path": rel_path_str,
                "line_number": lineno,
                "line_text": text.strip(),
                "context_before": list(context_before[-context_lines:]),
                "context_after": [],
            }
            context_before = []
            continue

        # Try '-' separator (context line)
        parts = line.split("-", 2)
        if len(parts) >= 3:
            filepath, lineno_str, text = parts[0], parts[1], parts[2]
            try:
                lineno = int(lineno_str.strip())
            except ValueError:
                continue
            if pending_match and filepath.strip() == current_file:
                pending_match["context_after"].append(text.strip())
            elif filepath.strip() == current_file or current_file is None:
                context_before.append(text.strip())
                current_file = filepath.strip()
            continue

    if pending_match:
        matches.append(pending_match)

    return matches


def _parse_grep_output(output: str, root: Path, context_lines: int) -> list[dict]:
    """Parse GNU grep --context output into structured match dicts."""
    matches = []
    context_before = []
    pending_match = None
    sep_re = re.compile(r"^(.*?)([:-])(\d+)([:-])(.*)$")

    for line in output.splitlines():
        if line == "--":
            # Group separator
            if pending_match:
                matches.append(pending_match)
                pending_match = None
            context_before = []
            continue

        m = sep_re.match(line)
        if not m:
            continue

        filepath = m.group(1).rstrip(":-")
        sep1 = m.group(2)
        lineno_str = m.group(3)
        sep2 = m.group(4)
        text = m.group(5)

        try:
            lineno = int(lineno_str)
        except ValueError:
            continue

        is_context = (sep2 == "-")

        if is_context:
            context_before.append(text.strip())
            continue

        # This is a match line
        if pending_match:
            matches.append(pending_match)

        rel_path_str = _try_rel_path(filepath, root)
        pending_match = {
            "path": rel_path_str,
            "line_number": lineno,
            "line_text": text.strip(),
            "context_before": list(context_before[-context_lines:]),
            "context_after": [],
        }
        context_before = []

    if pending_match:
        matches.append(pending_match)

    return matches


def _try_rel_path(filepath: str, root: Path) -> str:
    """Try to make filepath relative to root; return as-is on failure."""
    p = Path(filepath)
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return filepath


def daily_note(vault_root: str | Path, action: str, date: str | None = None,
               content: str | None = None, force: bool = False) -> dict:
    """Convenience for daily notes at memory/YYYY-MM-DD.md.

    action: 'read', 'append', or 'create'
    date: YYYY-MM-DD string, defaults to today
    content: required for append/create actions
    """
    if action not in ("read", "append", "create"):
        raise ValueError("action must be read, append, or create")
    if not date:
        date = datetime.date.today().isoformat()
    # Validate date format
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise ValueError(f"invalid date format: {date}, expected YYYY-MM-DD")
    rel = f"memory/{date}.md"
    root = Path(vault_root).expanduser().resolve()

    if action == "read":
        target = safe_resolve(root, rel)
        file_content = _read_text(target, force=force)
        return {
            "ok": True,
            "operation": "read",
            "path": rel,
            "content": file_content,
        }
    elif action == "append":
        if content is None:
            raise ValueError("--content is required for append action")
        return write_note(root, rel, content, mode="append", force=force)
    elif action == "create":
        if content is None:
            raise ValueError("--content is required for create action")
        return write_note(root, rel, content, mode="create", force=force)


# Architecture note: Mneme treats Markdown wikilinks as navigational source
# syntax, not the primary semantic graph. Moving a note should therefore be
# cheap by default; eager vault-wide wikilink rewrites are opt-in for Obsidian
# style workflows that need click-through links to stay current immediately.
def move_note(vault_root: str | Path, src_path: str, dst_path: str,
              dry_run: bool = False, force: bool = False, update_links: bool = False) -> dict:
    """Move a note, optionally updating matching [[wikilinks]] across the vault.

    - safe_resolve on both source and destination
    - atomic_write new file with source content
    - delete old file
    - when update_links=True, scan all .md files for [[old_stem]] wikilinks
      and replace with [[new_stem]]
    """
    root = Path(vault_root).expanduser().resolve()
    src = safe_resolve(root, src_path)
    dst = safe_resolve(root, dst_path)

    if not src.exists():
        raise ValueError(f"source note does not exist: {src_path}")

    if dst.exists() and not force:
        raise ValueError(f"destination already exists: {dst_path}; use --force to overwrite")

    old_content = src.read_text(encoding="utf-8")

    if dry_run:
        old_stem = src.stem
        new_stem = dst.stem
        links_updated = _count_wikilinks(root, old_stem) if update_links else 0
        return {
            "ok": True,
            "operation": "move",
            "old_path": rel_path(root, src),
            "new_path": rel_path(root, dst),
            "update_links": update_links,
            "links_updated": links_updated,
            "dry_run": True,
            "changed": True,
        }

    # Write new file
    atomic_write(dst, old_content)

    # Delete old file
    src.unlink()

    old_stem = src.stem
    new_stem = dst.stem
    links_updated = _update_wikilinks(root, old_stem, new_stem) if update_links else 0

    return {
        "ok": True,
        "operation": "move",
        "old_path": rel_path(root, src),
        "new_path": rel_path(root, dst),
        "update_links": update_links,
        "links_updated": links_updated,
        "changed": True,
    }


def _count_wikilinks(root: Path, stem: str) -> int:
    """Count wikilinks matching [[stem]] across the vault."""
    pattern = re.compile(rf"\[\[{re.escape(stem)}\]\]", re.IGNORECASE)
    count = 0
    for p in root.rglob("*.md"):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
            count += len(pattern.findall(text))
        except (OSError, ValueError):
            continue
    return count


def _update_wikilinks(root: Path, old_stem: str, new_stem: str) -> int:
    """Replace [[old_stem]] with [[new_stem]] across all .md files in the vault.

    Returns the total number of links updated.
    """
    pattern = re.compile(rf"\[\[{re.escape(old_stem)}\]\]", re.IGNORECASE)
    total = 0
    for p in root.rglob("*.md"):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        new_text, count = pattern.subn(f"[[{new_stem}]]", text)
        if count > 0:
            atomic_write(p, new_text)
            total += count
    return total


def delete_note(vault_root: str | Path, path: str, force: bool = False) -> dict:
    """Delete a note from the vault. Requires --force to confirm."""
    if not force:
        raise ValueError("deletion requires --force to confirm")
    root = Path(vault_root).expanduser().resolve()
    target = safe_resolve(root, path)
    if not target.exists():
        raise ValueError(f"note does not exist: {path}")
    rel = rel_path(root, target)
    target.unlink()
    return {
        "ok": True,
        "operation": "delete",
        "deleted_path": rel,
        "changed": True,
    }


def vault_status(vault_root: str | Path) -> dict:
    """Vault overview: total notes, notes per top-level folder, recent files."""
    root = Path(vault_root).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"vault root does not exist: {root}")

    folder_counts: dict[str, int] = {}
    total_notes = 0
    all_files = []

    for p in root.rglob("*.md"):
        if not p.is_file():
            continue
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            continue
        total_notes += 1
        top_folder = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        folder_counts[top_folder] = folder_counts.get(top_folder, 0) + 1
        mtime = p.stat().st_mtime
        all_files.append((rel.as_posix(), mtime))

    # Sort folders by count descending
    folders = [{"name": k, "count": v} for k, v in sorted(folder_counts.items(), key=lambda x: -x[1])]

    # 10 most recently modified
    all_files.sort(key=lambda x: -x[1])
    recent = []
    for fpath, mtime in all_files[:10]:
        dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
        recent.append({"path": fpath, "modified": dt.isoformat()})

    return {
        "ok": True,
        "operation": "status",
        "vault": str(root),
        "total_notes": total_notes,
        "folders": folders,
        "recent": recent,
    }

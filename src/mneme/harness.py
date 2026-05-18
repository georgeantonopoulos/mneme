from __future__ import annotations

import shlex
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


DEFAULT_TIMEOUT_SECONDS = 1800


def _echo_command() -> list[str]:
    return [
        sys.executable,
        "-c",
        "import sys; print(sys.stdin.read(), end='')",
    ]


BUILTIN_PROVIDERS: dict[str, list[str]] = {
    "echo": _echo_command(),
    "codex": ["codex", "exec", "--full-auto", "-"],
}


@dataclass
class HarnessResult:
    ok: bool
    provider: str
    command: list[str]
    cwd: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_command(command: str | Sequence[str]) -> list[str]:
    """Parse a command without using a shell."""
    if isinstance(command, str):
        argv = shlex.split(command)
    else:
        argv = [str(part) for part in command]
    if not argv:
        raise ValueError("command must not be empty")
    return argv


def command_for_provider(provider: str, command: str | Sequence[str] | None = None) -> list[str]:
    if command is not None:
        return parse_command(command)
    try:
        return list(BUILTIN_PROVIDERS[provider])
    except KeyError as exc:
        known = ", ".join(sorted(BUILTIN_PROVIDERS))
        raise ValueError(f"unknown provider '{provider}'; pass --command or use one of: {known}") from exc


def prepare_command(argv: Sequence[str], prompt: str) -> tuple[list[str], str | None]:
    """Return argv and stdin for a prompt.

    If an argv item contains ``{prompt}``, the prompt is inserted there and no
    stdin is sent. Otherwise the prompt is passed over stdin, keeping long
    prompts out of process listings.
    """
    has_prompt_placeholder = any("{prompt}" in part for part in argv)
    if has_prompt_placeholder:
        return [part.replace("{prompt}", prompt) for part in argv], None
    return list(argv), prompt


def run_llm(
    prompt: str,
    *,
    provider: str = "echo",
    command: str | Sequence[str] | None = None,
    cwd: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    env: Mapping[str, str] | None = None,
) -> HarnessResult:
    """Run a provider command with a prompt and capture the final output."""
    prompt = str(prompt or "")
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    cwd_path = Path(cwd).expanduser().resolve() if cwd is not None else None
    if cwd_path is not None and not cwd_path.exists():
        raise FileNotFoundError(f"cwd does not exist: {cwd_path}")
    if cwd_path is not None and not cwd_path.is_dir():
        raise NotADirectoryError(f"cwd is not a directory: {cwd_path}")

    base_command = command_for_provider(provider, command)
    argv, stdin = prepare_command(base_command, prompt)
    cwd_text = str(cwd_path) if cwd_path is not None else None
    child_env = None
    if env is not None:
        child_env = os.environ.copy()
        child_env.update({str(key): str(value) for key, value in env.items()})

    try:
        completed = subprocess.run(
            argv,
            input=stdin,
            text=True,
            capture_output=True,
            cwd=cwd_text,
            timeout=timeout,
            env=child_env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return HarnessResult(
            ok=False,
            provider=provider,
            command=argv,
            cwd=cwd_text,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            error=f"provider timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return HarnessResult(
            ok=False,
            provider=provider,
            command=argv,
            cwd=cwd_text,
            exit_code=None,
            stdout="",
            stderr="",
            error=str(exc),
        )

    return HarnessResult(
        ok=completed.returncode == 0,
        provider=provider,
        command=argv,
        cwd=cwd_text,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )

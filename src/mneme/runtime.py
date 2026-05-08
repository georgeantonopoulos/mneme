from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .core import DEFAULT_CONFIG_PATH, DEFAULT_HINTS, load_config


ENV_BY_NAME = {
    "db": "MNEME_DB",
    "vault": "MNEME_VAULT",
    "out": "MNEME_OUT",
}


def default_config_path() -> Path:
    return Path(os.environ.get("MNEME_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()


def load_runtime_config(config_path: Path | None = None) -> dict[str, Any]:
    path = Path(config_path or default_config_path()).expanduser()
    if not path.exists():
        return {}
    return load_config(path)


def resolve_path(args: Any, name: str, required: bool = True) -> Path | None:
    value = getattr(args, name, None)
    if value is not None:
        return Path(value).expanduser()
    env_name = ENV_BY_NAME.get(name)
    if env_name and os.environ.get(env_name):
        return Path(os.environ[env_name]).expanduser()
    cfg = load_runtime_config(getattr(args, "config", None))
    if cfg.get(name):
        return Path(cfg[name]).expanduser()
    if required:
        env_hint = f", set ${env_name}" if env_name else ""
        raise SystemExit(f"missing --{name}; provide it{env_hint}, or set it in a Mneme config file")
    return None


def resolve_hints(args: Any) -> list[str]:
    value = getattr(args, "hints", None)
    if value:
        return [p.strip() for p in value.split(",") if p.strip()]
    if os.environ.get("MNEME_HINTS"):
        return [p.strip() for p in os.environ["MNEME_HINTS"].split(",") if p.strip()]
    cfg = load_runtime_config(getattr(args, "config", None))
    hints = cfg.get("hints")
    if isinstance(hints, list):
        return [str(h) for h in hints]
    if isinstance(hints, str):
        return [p.strip() for p in hints.split(",") if p.strip()]
    return DEFAULT_HINTS


def config_as_json(config_path: Path | None = None) -> str:
    return json.dumps(load_runtime_config(config_path), indent=2, ensure_ascii=False)

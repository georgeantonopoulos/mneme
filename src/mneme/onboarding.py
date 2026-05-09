"""Interactive onboarding helpers for Mneme."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .core import DEFAULT_HINTS
from .path_classifier import DEFAULT_MODEL


@dataclass
class OnboardingAnswers:
    vault: Path
    db: Path
    out: Path
    hints: list[str] | None = None
    follow_symlinks: bool = False
    enable_gws: bool = False
    enable_classifier: bool = True
    classifier_provider: str = "ollama-cloud"
    classifier_model: str = DEFAULT_MODEL
    classifier_timeout: float = 2.0
    hermes_env_path: Path | None = None


def _expand(path: Path) -> str:
    return str(path.expanduser())


def build_config_payload(answers: OnboardingAnswers) -> dict:
    senses = [
        {
            "id": "vault",
            "type": "md",
            "enabled": True,
            "config": {"path": _expand(answers.vault), "follow_symlinks": answers.follow_symlinks},
        }
    ]
    if answers.enable_gws:
        senses.append(
            {
                "id": "gws",
                "type": "gws",
                "enabled": True,
                "config": {"email": True, "calendar": True, "tasks": True},
            }
        )
    payload = {
        "vault": _expand(answers.vault),
        "db": _expand(answers.db),
        "out": _expand(answers.out),
        "hints": answers.hints or DEFAULT_HINTS,
        "follow_symlinks": answers.follow_symlinks,
        "senses": senses,
        "path_classifier": {
            "enabled": answers.enable_classifier,
            "provider": answers.classifier_provider,
            "model": answers.classifier_model,
            "timeout": answers.classifier_timeout,
            "strip_injected_context": True,
            "fallback": "conservative_regex",
        },
    }
    if answers.hermes_env_path:
        payload["hermes"] = {"env_path": _expand(answers.hermes_env_path)}
    return payload


def render_summary(config_path: Path, payload: dict) -> str:
    classifier = payload.get("path_classifier", {})
    env_lines = [
        f"export MNEME_CONFIG={config_path}",
        f"export MNEME_PATH_CLASSIFIER_MODEL={classifier.get('model', DEFAULT_MODEL)}",
        f"export MNEME_PATH_CLASSIFIER_TIMEOUT={classifier.get('timeout', 2.0)}",
    ]
    return "\n".join(
        [
            "Mneme setup complete.",
            f"Config: {config_path}",
            f"Vault: {payload.get('vault')}",
            f"Database: {payload.get('db')}",
            f"Classifier: {classifier.get('provider')} / {classifier.get('model')} (enabled={classifier.get('enabled')})",
            "",
            "Suggested environment:",
            *env_lines,
            "",
            "Next steps:",
            "1. mneme doctor",
            "2. mneme sense run md --json",
            "3. mneme tick --surface --json",
            "4. For Hermes, add the classifier env vars to your Hermes .env and restart the gateway/session.",
        ]
    )


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def _ask_bool(prompt: str, default: bool = False) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{default_text}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def _ask_choice(prompt: str, choices: list[str], default: str) -> str:
    print(prompt)
    for idx, choice in enumerate(choices, 1):
        marker = " (recommended)" if choice == default else ""
        print(f"  {idx}. {choice}{marker}")
    raw = _ask("Choose", str(choices.index(default) + 1))
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        return choices[int(raw) - 1]
    if raw in choices:
        return raw
    return default


def run_onboarding(config_path: Path, *, force: bool = False) -> dict:
    if config_path.exists() and not force:
        raise FileExistsError(f"config already exists: {config_path}; pass --force to overwrite")
    print("Mneme setup")
    print("-----------")
    print("This will configure your vault, senses, and optional Hermes path classifier.\n")
    vault = Path(_ask("Markdown vault path", str(Path.cwd()))).expanduser()
    default_base = Path.home() / ".local" / "share" / "mneme"
    db = Path(_ask("SQLite database path", str(default_base / "mneme.sqlite"))).expanduser()
    out = Path(_ask("Output/cards directory", str(default_base / "out"))).expanduser()
    enable_gws = _ask_bool("Enable Google Workspace sense via local gws command?", False)
    enable_classifier = _ask_bool("Enable Hermes prompt path classifier?", True)
    provider = "ollama-cloud"
    model = DEFAULT_MODEL
    timeout = 2.0
    hermes_env = None
    if enable_classifier:
        provider = _ask_choice("Classifier provider", ["ollama-cloud", "local-ollama", "disabled"], "ollama-cloud")
        if provider == "disabled":
            enable_classifier = False
        elif provider == "ollama-cloud":
            model = _ask_choice("Classifier model", ["gemma4:31b", "deepseek-v4-flash", "custom"], "gemma4:31b")
            if model == "custom":
                model = _ask("Model name", DEFAULT_MODEL)
            hermes_env = Path(_ask("Hermes .env path", str(Path.home() / ".hermes" / ".env"))).expanduser()
        else:
            model = _ask_choice("Local Ollama classifier model", ["qwen3.5:0.8b", "qwen2.5:0.5b-instruct", "smollm2:360m-instruct-q4_K_M", "custom"], "qwen3.5:0.8b")
            if model == "custom":
                model = _ask("Model name", "qwen3.5:0.8b")
        timeout = float(_ask("Classifier timeout seconds", "2.0"))
    answers = OnboardingAnswers(
        vault=vault,
        db=db,
        out=out,
        enable_gws=enable_gws,
        enable_classifier=enable_classifier,
        classifier_provider=provider,
        classifier_model=model,
        classifier_timeout=timeout,
        hermes_env_path=hermes_env,
    )
    payload = build_config_payload(answers)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "config": str(config_path), "payload": payload, "summary": render_summary(config_path, payload)}

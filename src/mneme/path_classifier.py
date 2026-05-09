"""Prompt path classifier for Mneme hooks.

Classifies raw user text into one of three memory-processing paths:
``retrieval``, ``correction``, or ``both``.  The model path is optional and
safe-by-default: callers may inject a provider, or use the Ollama Cloud
OpenAI-compatible API via environment variables.  If anything fails, Mneme uses
an intentionally conservative regex fallback.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable, Literal, TypedDict

PathLabel = Literal["retrieval", "correction", "both"]


class Classification(TypedDict, total=False):
    path: PathLabel
    confidence: float
    reason: str
    source: str
    error: str


DEFAULT_MODEL = "gemma4:31b"
DEFAULT_BASE_URL = "https://ollama.com/v1"

_SYSTEM_PROMPT = """You are a strict 3-label classifier for a memory assistant. Output only JSON.
Labels:
correction = user says assistant/memory is wrong, contradicts a role/fact/status, says done/paid/resolved, dismisses stale info, or says phrases like "what are you talking about", "I'm the tenant", "that's wrong", "already paid".
retrieval = user asks a normal question/request or continues a task with no correction.
both = user corrects/contradicts AND asks for help/search/action.
Priority: if any correction signal is present, NEVER choose retrieval. Choose both only if there is also an action/request question.
Return exactly: {"path":"retrieval|correction|both","confidence":0.0,"reason":"short"}"""

_FEW_SHOT: list[tuple[str, str]] = [
    ("What are you talking about, I'm the tenant", '{"path":"correction","confidence":0.99,"reason":"contradicts prior role assumption"}'),
    ("Actually I'm the tenant, what should I clean before 5pm?", '{"path":"both","confidence":0.99,"reason":"corrects role and asks for cleaning advice"}'),
    ("Yes good observation, I need to clean the place", '{"path":"retrieval","confidence":0.85,"reason":"continues normal task"}'),
    ("Yes good observation, I need to clean the place for the viewing at 5pm", '{"path":"retrieval","confidence":0.9,"reason":"continues task; no correction"}'),
    ("That PCN is already paid, stop surfacing it", '{"path":"correction","confidence":0.99,"reason":"marks surfaced item resolved"}'),
    ("No, that's wrong, check Gmail", '{"path":"both","confidence":0.99,"reason":"rejects claim and requests lookup"}'),
]

_CORRECTION_PATTERNS = [
    r"(?<!\bnot\s)(?<!\bnever\s)(?<!\bwill\s)(?<!\bstill\s)(?<!\bpartially\s)(?<!\bhalf-)\b(?:resolved|done|fixed|sorted|closed|paid|sent|booked|confirmed)\b",
    r"\b(?:not urgent|no longer|ignore|don't worry|all good|fine now)\b",
    r"\b(?:moot|irrelevant|secondary|forget)\b",
    r"\b(?:correct(?:\s+that|ion)?):",
    r"\b(?:that'?s wrong|that'?s stale|hallucinat)\b",
    r"\bwhat\s+are\s+you\s+talking\s+about\b",
    r"\b(?:actually|no[,.])\b",
    r"\b(?:i'?m|i\s+am)\s+(?:the\s+)?(?:tenant|landlord|owner|agent|buyer|seller|client|customer|parent|guardian)\b",
    r"\b(?:mark\s+(?:as\s+)?|this\s+is\s+now)\s+(?:resolved|done|closed|paid|moot)",
    r"\b(?:update\s+(?:status|label|tag|memory)|change\s+(?:status|label|tag))\b",
    r"\bnot urgent\b",
    r"\[silent\]",
]

_REQUEST_PATTERNS = [
    r"\?",
    r"\b(?:check|search|find|look\s+up|why|how|tell|show|please|can\s+you|could\s+you|should\s+i|need\s+to)\b",
]

Provider = Callable[[str], str]


def strip_injected_context(user_message: str) -> str:
    """Return only the raw user message, excluding Mneme/system hook text.

    Hermes hook payloads may include prompt-time retrieved context before the
    actual message and, during debugging, generated Mneme path instructions after
    it.  The classifier must never let either side influence the route.
    """
    if not user_message:
        return ""
    text = user_message.strip()
    marker = "[Prompt-time retrieved context"
    if text.startswith(marker):
        for end_marker in ("\n[User message]\n", "\n\n[User message]\n"):
            pos = text.find(end_marker)
            if pos != -1:
                text = text[pos + len(end_marker) :].strip()
                break
    cut = len(text)
    for leak_marker in (
        "\n\nMNEME RETRIEVAL PATH",
        "\n\nMNEME CORRECTION PATH",
        "\n\n━━━━━━━━━━━━━━━━",
        "\nPath tag (internal):",
    ):
        idx = text.find(leak_marker)
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut].strip()


def conservative_regex_classify(user_message: str) -> Classification:
    text = strip_injected_context(user_message)
    lower = text.lower()
    has_correction = any(re.search(pattern, lower) for pattern in _CORRECTION_PATTERNS)
    has_request = any(re.search(pattern, lower) for pattern in _REQUEST_PATTERNS)
    if has_correction and has_request:
        path: PathLabel = "both"
    elif has_correction:
        path = "correction"
    else:
        path = "retrieval"
    return {
        "path": path,
        "confidence": 0.85 if has_correction else 0.7,
        "reason": "conservative fallback classifier",
        "source": "fallback",
    }


def _build_messages(user_message: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for user, assistant in _FEW_SHOT:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": user_message})
    return messages


def build_prompt(user_message: str) -> str:
    """Build a readable prompt for non-chat provider callables/tests."""
    parts = [_SYSTEM_PROMPT, "Examples:"]
    for user, assistant in _FEW_SHOT:
        parts.append(f"User: {user}\nJSON: {assistant}")
    parts.append(f"User: {user_message}\nJSON:")
    return "\n\n".join(parts)


def parse_classification(text: str) -> Classification:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("classifier returned no JSON object")
    data = json.loads(match.group(0))
    path = data.get("path")
    if path not in {"retrieval", "correction", "both"}:
        raise ValueError(f"invalid path: {path!r}")
    confidence = float(data.get("confidence", 0.0))
    return {
        "path": path,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": str(data.get("reason") or "model classifier"),
        "source": "model",
    }


def ollama_cloud_provider(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = 2.0,
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """Call Ollama Cloud's OpenAI-compatible chat completions endpoint."""
    bearer = api_key or os.getenv("OLLAMA_API_KEY")
    if not bearer:
        raise RuntimeError("OLLAMA_API_KEY is not set")
    base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": _build_messages(prompt),
        "temperature": 0,
        "max_tokens": 80,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + bearer, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec: URL is explicit/configured
        body = json.loads(response.read().decode("utf-8"))
    return (body["choices"][0]["message"].get("content") or "").strip()


def classify_path(
    user_message: str,
    *,
    provider: Callable[..., str] | None = None,
    model: str | None = None,
    timeout: float = 2.0,
    api_key: str | None = None,
    base_url: str | None = None,
    enabled: bool = True,
) -> Classification:
    clean = strip_injected_context(user_message)
    if not enabled:
        return conservative_regex_classify(clean)
    provider = provider or ollama_cloud_provider
    model = model or os.getenv("MNEME_PATH_CLASSIFIER_MODEL") or DEFAULT_MODEL
    try:
        prompt = build_prompt(clean)
        kwargs = {"model": model, "timeout": timeout, "base_url": base_url}
        kwargs["api" + "_key"] = api_key
        raw = provider(prompt, **kwargs)
        result = parse_classification(raw)
        return result
    except Exception as exc:
        fallback = conservative_regex_classify(clean)
        fallback["error"] = str(exc)
        return fallback

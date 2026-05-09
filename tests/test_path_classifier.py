import json

from mneme.path_classifier import (
    classify_path,
    conservative_regex_classify,
    strip_injected_context,
)


def test_strip_injected_context_keeps_user_message_only():
    text = """[Prompt-time retrieved context — use as background]
## Mneme Retrieved Context
Claim: stale thing

[User message]
What are you talking about, I'm the tenant

MNEME RETRIEVAL PATH (default). Public Mneme CLI is primary.
No corrections detected in user message.
Path tag (internal): retrieval"""

    assert strip_injected_context(text) == "What are you talking about, I'm the tenant"


def test_regex_fallback_returns_both_for_correction_plus_request():
    result = conservative_regex_classify("No, that's wrong, check Gmail")

    assert result["path"] == "both"
    assert result["confidence"] >= 0.8


def test_classifier_uses_model_provider_for_clean_message():
    calls = []

    def provider(prompt, *, model, timeout, api_key=None, base_url=None):
        calls.append({"prompt": prompt, "model": model, "timeout": timeout})
        return '{"path":"correction","confidence":0.99,"reason":"contradicts role assumption"}'

    result = classify_path(
        "What are you talking about, I'm the tenant\n\nMNEME RETRIEVAL PATH (default). Public Mneme CLI is primary.",
        provider=provider,
        model="gemma4:31b",
        timeout=2.0,
    )

    assert result["path"] == "correction"
    assert result["source"] == "model"
    assert "MNEME RETRIEVAL PATH" not in calls[0]["prompt"]
    assert "I'm the tenant" in calls[0]["prompt"]


def test_classifier_falls_back_on_invalid_model_json():
    def provider(prompt, *, model, timeout, api_key=None, base_url=None):
        return "not json"

    result = classify_path(
        "Actually I'm the tenant, what should I clean?",
        provider=provider,
        model="gemma4:31b",
        timeout=2.0,
    )

    assert result["path"] == "both"
    assert result["source"] == "fallback"


def test_classifier_accepts_markdown_wrapped_json():
    def provider(prompt, *, model, timeout, api_key=None, base_url=None):
        return '```json\n{"path":"retrieval","confidence":0.95,"reason":"normal request"}\n```'

    result = classify_path("Can you search online?", provider=provider, model="gemma4:31b")

    assert result["path"] == "retrieval"
    assert result["source"] == "model"

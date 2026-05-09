import json
from pathlib import Path

from mneme.onboarding import OnboardingAnswers, build_config_payload, render_summary


def test_build_config_payload_includes_vault_senses_and_classifier():
    answers = OnboardingAnswers(
        vault=Path('/tmp/vault'),
        db=Path('/tmp/mneme.sqlite'),
        out=Path('/tmp/out'),
        enable_gws=True,
        enable_classifier=True,
        classifier_provider='ollama-cloud',
        classifier_model='gemma4:31b',
        classifier_timeout=2.0,
        hermes_env_path=Path('/tmp/.env'),
    )

    payload = build_config_payload(answers)

    assert payload['vault'] == '/tmp/vault'
    assert {'id': 'vault', 'type': 'md', 'enabled': True, 'config': {'path': '/tmp/vault', 'follow_symlinks': False}} in payload['senses']
    assert any(s['type'] == 'gws' for s in payload['senses'])
    assert payload['path_classifier'] == {
        'enabled': True,
        'provider': 'ollama-cloud',
        'model': 'gemma4:31b',
        'timeout': 2.0,
        'strip_injected_context': True,
        'fallback': 'conservative_regex',
    }
    assert payload['hermes']['env_path'] == '/tmp/.env'


def test_render_summary_shows_next_steps():
    answers = OnboardingAnswers(vault=Path('/tmp/vault'), db=Path('/tmp/db.sqlite'), out=Path('/tmp/out'))
    payload = build_config_payload(answers)

    summary = render_summary(Path('/tmp/config.json'), payload)

    assert 'mneme doctor' in summary
    assert 'mneme sense run md' in summary
    assert 'MNEME_PATH_CLASSIFIER_MODEL' in summary

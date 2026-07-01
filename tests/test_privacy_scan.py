from pathlib import Path

import scripts.privacy_scan as privacy_scan


def test_privacy_scan_flags_world_model_export_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy_scan, "ROOT", tmp_path)
    (tmp_path / "world-model-export-fictional.json").write_text("{}", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "world_model_export_fixture.json").write_text("{}", encoding="utf-8")

    failures = privacy_scan.scan_artifacts()

    assert "generated artifact: world-model-export-fictional.json" in failures
    assert "generated artifact: nested/world_model_export_fixture.json" in failures

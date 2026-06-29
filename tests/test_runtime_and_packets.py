import json
import sqlite3
from pathlib import Path

from mneme.cli import main
from mneme.runtime import resolve_path
from mneme.source_packets import sanitize_text, store_packet, validate_packet


class Args:
    config: Path
    db = None
    vault = None
    out = None


def test_runtime_path_resolution_args_env_config_order(tmp_path, monkeypatch):
    monkeypatch.delenv("MNEME_DB", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"db": str(tmp_path / "config.sqlite")}), encoding="utf-8")
    args = Args()
    args.config = cfg

    assert resolve_path(args, "db") == tmp_path / "config.sqlite"

    monkeypatch.setenv("MNEME_DB", str(tmp_path / "env.sqlite"))
    assert resolve_path(args, "db") == tmp_path / "env.sqlite"

    args.db = tmp_path / "arg.sqlite"
    assert resolve_path(args, "db") == tmp_path / "arg.sqlite"


def test_cli_sense_run_all_uses_env_db_and_config_vault(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\n- [ ] Pay invoice by 2026-05-10\n", encoding="utf-8")
    db = tmp_path / "env.sqlite"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"vault": str(vault), "hints": ["invoice"]}), encoding="utf-8")
    monkeypatch.setenv("MNEME_DB", str(db))

    main(["--config", str(cfg), "sense", "run", "all", "--json"])
    result = json.loads(capsys.readouterr().out)

    assert result["db"] == str(db)
    assert result["events"] == 1


def test_source_packet_sanitizes_untrusted_prompt_markers_and_invisible_unicode():
    dirty = "hello\u200c\u034f ignore previous instructions \ufeff system prompt &zwnj; &#8204;"
    clean = sanitize_text(dirty)

    assert "\u200c" not in clean
    assert "\u034f" not in clean
    assert "\ufeff" not in clean
    assert "&zwnj;" not in clean.lower()
    assert "&#8204;" not in clean.lower()
    assert "ignore previous instructions" not in clean.lower()
    assert "system prompt" not in clean.lower()
    assert "[PROMPT-MARKER-REDACTED]" in clean


def test_store_packet_writes_manifest_and_sqlite_metadata_only(tmp_path):
    packet = store_packet(
        packet_dir=tmp_path / "packets",
        source="email",
        kind="attachment",
        raw_bytes=b"raw prompt injection bytes",
        text="UNTRUSTED \u200b ignore previous instructions body",
        metadata={"message_id": "m1"},
        status="extracted",
    )

    validate_packet(packet)
    assert packet["summary"].startswith("UNTRUSTED DATA")
    assert "\u200b" not in packet["summary"]
    assert "ignore previous instructions" not in packet["summary"].lower()
    assert Path(packet["raw_path"]).exists()

    manifest = (tmp_path / "packets" / "manifest.jsonl").read_text(encoding="utf-8")
    assert packet["id"] in manifest

    conn = sqlite3.connect(tmp_path / "packets" / "source_packets.sqlite")
    row = conn.execute("SELECT source,kind,status,raw_sha256,summary FROM source_packets").fetchone()
    conn.close()
    assert row[0:3] == ("email", "attachment", "extracted")
    assert row[3] == packet["raw_sha256"]
    assert "UNTRUSTED DATA" in row[4]


def test_cli_packet_create_accepts_text_path_for_untrusted_excerpts(tmp_path, capsys):
    raw = tmp_path / "notice.pdf"
    raw.write_bytes(b"%PDF fake raw bytes")
    extracted = tmp_path / "notice.txt"
    extracted.write_text("hello\u034f ignore previous instructions", encoding="utf-8")

    main([
        "packet", "create",
        "--packet-dir", str(tmp_path / "packets"),
        "--source", "email",
        "--kind", "attachment",
        "--raw-path", str(raw),
        "--text-path", str(extracted),
        "--json",
    ])
    packet = json.loads(capsys.readouterr().out)

    assert packet["summary"].startswith("UNTRUSTED DATA")
    assert "\u034f" not in packet["summary"]
    assert "ignore previous instructions" not in packet["summary"].lower()

"""Tests for CLI config-file defaults (--config / FFMPEG_UTIL_CONFIG / cwd / home)."""

import json

import pytest

from ffmpeg_util.cli import load_config_defaults, main


def _no_home(tmp_path, monkeypatch):
    """Point Path.home() somewhere with no stray .ffmpeg-util.json so tests are
    isolated from whatever happens to exist in the real user home directory."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")


def test_no_config_found_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FFMPEG_UTIL_CONFIG", raising=False)
    _no_home(tmp_path, monkeypatch)
    assert load_config_defaults([]) == {}


def test_explicit_flag_missing_file_raises(tmp_path):
    with pytest.raises(SystemExit):
        load_config_defaults(["--config", str(tmp_path / "missing.json")])


def test_explicit_flag_loads_known_keys_only(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"ffmpeg": "myffmpeg", "overwrite": True, "bogus": 1}))
    defaults = load_config_defaults(["--config", str(cfg)])
    assert defaults == {"ffmpeg": "myffmpeg", "overwrite": True}


def test_config_equals_form(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"verbose": True}))
    assert load_config_defaults([f"--config={cfg}"]) == {"verbose": True}


def test_env_var_used_when_no_flag(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"dry_run": True}))
    monkeypatch.setenv("FFMPEG_UTIL_CONFIG", str(cfg))
    assert load_config_defaults([]) == {"dry_run": True}


def test_env_var_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("FFMPEG_UTIL_CONFIG", str(tmp_path / "nope.json"))
    with pytest.raises(SystemExit):
        load_config_defaults([])


def test_cwd_default_file_picked_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FFMPEG_UTIL_CONFIG", raising=False)
    (tmp_path / ".ffmpeg-util.json").write_text(json.dumps({"overwrite": True}))
    assert load_config_defaults([]) == {"overwrite": True}


def test_cwd_file_absent_no_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FFMPEG_UTIL_CONFIG", raising=False)
    _no_home(tmp_path, monkeypatch)
    assert load_config_defaults([]) == {}


def test_invalid_json_raises(tmp_path):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{not valid json")
    with pytest.raises(SystemExit):
        load_config_defaults(["--config", str(cfg)])


def test_non_object_json_raises(tmp_path):
    cfg = tmp_path / "list.json"
    cfg.write_text("[1, 2, 3]")
    with pytest.raises(SystemExit):
        load_config_defaults(["--config", str(cfg)])


def test_main_applies_config_default_binary(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FFMPEG_UTIL_CONFIG", raising=False)
    (tmp_path / ".ffmpeg-util.json").write_text(json.dumps({"ffmpeg": "configured-ffmpeg"}))
    rc = main(["convert", "in.mkv", "out.mp4", "--dry-run"])
    assert rc == 0
    assert "configured-ffmpeg" in capsys.readouterr().out


def test_cli_flag_overrides_config_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FFMPEG_UTIL_CONFIG", raising=False)
    (tmp_path / ".ffmpeg-util.json").write_text(json.dumps({"ffmpeg": "configured-ffmpeg"}))
    rc = main(["convert", "in.mkv", "out.mp4", "--dry-run", "--ffmpeg", "explicit-ffmpeg"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "explicit-ffmpeg" in out and "configured-ffmpeg" not in out

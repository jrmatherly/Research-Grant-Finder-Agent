import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "verify-on-stop.sh"
SETTINGS = REPO / ".claude" / "settings.json"
BASH = shutil.which("bash") or ""

needs_shell = pytest.mark.skipif(not BASH or shutil.which("jq") is None, reason="needs bash and jq")


def run_hook(payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env)


@needs_shell
def test_stop_hook_exits_when_already_active() -> None:
    assert run_hook({"stop_hook_active": True}).returncode == 0


@needs_shell
def test_stop_hook_skips_when_tools_are_missing(tmp_path: Path) -> None:
    assert run_hook({"stop_hook_active": False}, env={"PATH": str(tmp_path)}).returncode == 0


@needs_shell
def test_stop_hook_skips_without_jq_even_when_tests_would_fail(tmp_path: Path) -> None:
    (tmp_path / "uv").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (tmp_path / "git").write_text("#!/bin/sh\necho ' M changed.py'\n", encoding="utf-8")
    for stub in ("uv", "git"):
        (tmp_path / stub).chmod(0o755)
    env = {"PATH": str(tmp_path), "CLAUDE_PROJECT_DIR": str(REPO)}
    assert run_hook({"stop_hook_active": True}, env=env).returncode == 0


def test_settings_registers_stop_hook() -> None:
    stop = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
    assert stop["type"] == "command"
    assert stop["command"].endswith("/.claude/hooks/verify-on-stop.sh")


def test_settings_denies_edits_to_generated_output() -> None:
    deny = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    assert deny == ["Edit(/NIH Extractor/data/**)", "Edit(/NIH Extractor/outputs/**)", "Edit(/NIH Extractor/digests/**)"]

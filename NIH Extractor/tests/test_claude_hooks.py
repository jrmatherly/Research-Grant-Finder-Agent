import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "verify-on-stop.sh"
SETTINGS = REPO / ".claude" / "settings.json"
BASH = shutil.which("bash") or ""

needs_shell = pytest.mark.skipif(not BASH or shutil.which("jq") is None, reason="needs bash and jq")


def run_hook(tmp_path: Path, active: bool, stubs: dict[str, str], real_path: bool) -> int:
    # Every case either stubs uv ahead of the real one or hides it, so a test can never start pytest inside pytest.
    for name, body in stubs.items():
        (tmp_path / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (tmp_path / name).chmod(0o755)
    path = f"{tmp_path}{os.pathsep}{os.environ['PATH']}" if real_path else str(tmp_path)
    payload = json.dumps({"stop_hook_active": active})
    return subprocess.run([BASH, str(HOOK)], input=payload, capture_output=True, text=True, env={**os.environ, "PATH": path}, cwd=tmp_path, timeout=30).returncode


@needs_shell
def test_stop_hook_blocks_when_tests_fail(tmp_path: Path) -> None:
    # This stub fails only when the hook runs `uv run` from the directory that holds the dashboard.
    assert run_hook(tmp_path, active=False, stubs={"uv": '[ -f streamlit_app.py ] && [ "$1" = run ] && exit 1; exit 0'}, real_path=True) == 2


@needs_shell
def test_stop_hook_allows_stop_when_tests_pass(tmp_path: Path) -> None:
    assert run_hook(tmp_path, active=False, stubs={"uv": "exit 0"}, real_path=True) == 0


@needs_shell
def test_stop_hook_exits_when_already_active(tmp_path: Path) -> None:
    assert run_hook(tmp_path, active=True, stubs={"uv": "exit 1"}, real_path=True) == 0


@needs_shell
def test_stop_hook_skips_without_jq(tmp_path: Path) -> None:
    assert run_hook(tmp_path, active=True, stubs={"uv": "exit 1"}, real_path=False) == 0


@needs_shell
def test_stop_hook_skips_without_uv(tmp_path: Path) -> None:
    assert run_hook(tmp_path, active=False, stubs={"jq": "echo false"}, real_path=False) == 0


def test_settings_registers_stop_hook() -> None:
    stop = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
    assert stop["type"] == "command"
    assert stop["command"].endswith("/.claude/hooks/verify-on-stop.sh")


def test_settings_denies_edits_to_generated_output() -> None:
    deny = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    assert deny == ["Edit(/NIH Extractor/data/**)", "Edit(/NIH Extractor/outputs/**)", "Edit(/NIH Extractor/digests/**)"]

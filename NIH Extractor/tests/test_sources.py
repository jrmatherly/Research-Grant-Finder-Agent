import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "nih_grant_matcher").glob("*.py")) + [ROOT / "streamlit_app.py"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_file_compiles(path: Path) -> None:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize("module", ["nih_grant_matcher.cli", "nih_grant_matcher.workflow"])
def test_entry_module_imports(module: str) -> None:
    importlib.import_module(module)

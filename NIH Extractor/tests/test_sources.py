import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "nih_grant_matcher").glob("*.py")) + [ROOT / "streamlit_app.py"]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_file_compiles(path: Path) -> None:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize("module", ["nih_grant_matcher.__main__", "nih_grant_matcher.cli", "nih_grant_matcher.workflow"])
def test_entry_module_imports(module: str) -> None:
    importlib.import_module(module)


def test_dashboard_imports_names_that_exist() -> None:
    # The dashboard needs streamlit, which the tests do not install, so check its package imports without running it.
    tree = ast.parse((ROOT / "streamlit_app.py").read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("nih_grant_matcher")]
    assert imports
    for node in imports:
        module = importlib.import_module(node.module or "")
        for alias in node.names:
            assert hasattr(module, alias.name), f"{node.module} has no {alias.name}"

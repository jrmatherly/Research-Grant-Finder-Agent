import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "nih_grant_matcher"

def test_only_the_ui_modules_import_streamlit() -> None:
    for path in PACKAGE.rglob("*.py"):
        names = {alias.name.split(".")[0] for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in ([ast.alias(node.module or "")] if isinstance(node, ast.ImportFrom) else node.names)}
        assert ("streamlit" in names or "pandas" in names) <= (path.parent.name == "ui"), path

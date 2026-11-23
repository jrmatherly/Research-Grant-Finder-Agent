import importlib.util
import sys
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parent.parent / "macos" / "launcher.py"


def _load(monkeypatch):
    # A None entry makes the import fail, as on Linux CI where the macos group is not installed.
    for name in ("webview", "streamlit", "streamlit.web"):
        monkeypatch.setitem(sys.modules, name, None)
    spec = importlib.util.spec_from_file_location("grant_matcher_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_binds_loopback_on_the_given_port_and_runs_the_dashboard(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    argv = launcher.server_argv(Path("/bundle/streamlit_app.py"), 51234)
    assert argv[:3] == ["streamlit", "run", "/bundle/streamlit_app.py"]
    assert "--server.address=127.0.0.1" in argv and "--server.port=51234" in argv and "--server.headless=true" in argv
    assert "--browser.gatherUsageStats=false" in argv


def test_unfrozen_launcher_serves_the_repository_dashboard(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    assert launcher.app_script() == LAUNCHER.parent.parent / "streamlit_app.py"
    assert launcher.app_script().is_file()


def test_data_and_log_live_under_the_given_home(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    assert launcher.data_dir(tmp_path) == tmp_path / "Library" / "Application Support" / "Grant Matcher"
    assert launcher.log_path(tmp_path) == tmp_path / "Library" / "Logs" / "Grant Matcher" / "server.log"


def test_status_page_escapes_the_message(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    html = launcher.page("See the log at /Users/a&b/<log>")
    assert "/Users/a&amp;b/&lt;log&gt;" in html and "<log>" not in html

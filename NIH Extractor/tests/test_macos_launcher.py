import http.server
import importlib.util
import subprocess
import sys
import threading
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
    # Without this a page whose domain is rebound to 127.0.0.1 can drive the dashboard.
    assert "--server.allowedHosts=127.0.0.1" in argv


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


class _Window:
    def __init__(self) -> None:
        self.shown: list[tuple[str, str]] = []
    def load_url(self, url: str) -> None:
        self.shown.append(("url", url))
    def load_html(self, html: str) -> None:
        self.shown.append(("html", html))


class _Child:
    pid = 4242
    def __init__(self, exit_code: int | None = None) -> None:
        self.exit_code, self.terminated = exit_code, False
    def poll(self) -> int | None:
        return self.exit_code
    def terminate(self) -> None:
        self.terminated = True


class _Healthy(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args) -> None:
        pass


def _healthy_server_url() -> str:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Healthy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


def _lsof_reports(monkeypatch, launcher, pids: str) -> None:
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=pids))


def test_window_loads_the_dashboard_from_its_own_server_even_behind_a_proxy(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    _lsof_reports(monkeypatch, launcher, "4242\n")
    window, child, url = _Window(), _Child(), _healthy_server_url()
    launcher.wait_and_load(window, child, url, tmp_path / "server.log")
    assert window.shown == [("url", url)] and not child.terminated


def test_window_refuses_a_server_that_is_not_its_child(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    _lsof_reports(monkeypatch, launcher, "999\n")
    window, child = _Window(), _Child()
    launcher.wait_and_load(window, child, _healthy_server_url(), tmp_path / "server.log")
    assert [kind for kind, _ in window.shown] == ["html"] and "server.log" in window.shown[0][1] and child.terminated


def test_window_names_the_log_when_the_server_exits(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    window = _Window()
    launcher.wait_and_load(window, _Child(exit_code=1), "http://127.0.0.1:9", tmp_path / "server.log")
    assert [kind for kind, _ in window.shown] == ["html"] and str(tmp_path / "server.log") in window.shown[0][1]

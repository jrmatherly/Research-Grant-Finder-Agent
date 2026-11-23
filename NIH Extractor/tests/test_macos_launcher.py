import http.server
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import types

import pytest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parent.parent / "macos" / "launcher.py"


def _load(monkeypatch):
    # A None entry makes the import fail: webview is absent on Linux CI, and loading the launcher must import neither package.
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
    assert "--browser.gatherUsageStats=false" in argv and "--global.developmentMode=false" in argv and "--server.fileWatcherType=none" in argv
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


def _lsof_reports(monkeypatch, launcher, pids: str) -> list[list[str]]:
    calls: list[list[str]] = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=pids)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    return calls


def test_window_loads_the_dashboard_from_its_own_server_even_behind_a_proxy(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    calls = _lsof_reports(monkeypatch, launcher, "4242\n")
    window, child, url = _Window(), _Child(), _healthy_server_url()
    launcher.wait_and_load(window, child, url, tmp_path / "server.log")
    assert window.shown == [("url", url)] and not child.terminated
    assert f"-iTCP:{url.rsplit(':', 1)[1]}" in calls[0] and "-sTCP:LISTEN" in calls[0]


def test_window_refuses_a_server_that_is_not_its_child(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    _lsof_reports(monkeypatch, launcher, "999\n")
    window, child = _Window(), _Child()
    launcher.wait_and_load(window, child, _healthy_server_url(), tmp_path / "server.log")
    assert [kind for kind, _ in window.shown] == ["html"] and "held by another process" in window.shown[0][1] and child.terminated
    assert "held by another process" in (tmp_path / "server.log").read_text()


def test_window_names_the_log_and_the_exit_code_when_the_server_exits(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    window, child = _Window(), _Child(exit_code=3)
    launcher.wait_and_load(window, child, "http://127.0.0.1:9", tmp_path / "server.log")
    assert [kind for kind, _ in window.shown] == ["html"] and child.terminated
    assert str(tmp_path / "server.log") in window.shown[0][1] and "exited with code 3" in window.shown[0][1]


def test_window_shows_the_error_page_when_the_wait_itself_fails(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setattr(launcher, "start_failure", lambda child, url: 1 / 0)
    window, child = _Window(), _Child()
    launcher.wait_and_load(window, child, "http://127.0.0.1:9", tmp_path / "server.log")
    assert [kind for kind, _ in window.shown] == ["html"] and "ZeroDivisionError" in (tmp_path / "server.log").read_text() and child.terminated


def test_a_listener_that_does_not_speak_http_is_not_taken_for_the_server(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    listener = socket.create_server(("127.0.0.1", 0))
    def answer() -> None:
        while True:
            conn, _ = listener.accept()
            conn.sendall(b"not http\r\n\r\n")
            conn.close()
    threading.Thread(target=answer, daemon=True).start()
    ticks = iter(range(0, 1000, 30))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    assert launcher.start_failure(_Child(), f"http://127.0.0.1:{listener.getsockname()[1]}") == "its server did not answer within 60 seconds"


def test_port_ownership_matches_whole_process_ids_among_listeners(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    for listeners, owned in (("7\n4242\n", True), ("14242\n42420\n", False), ("", False)):
        _lsof_reports(monkeypatch, launcher, listeners)
        assert launcher.owns_port(4242, "5000") is owned


@pytest.mark.parametrize("error", [FileNotFoundError("lsof"), subprocess.TimeoutExpired("lsof", 5)])
def test_port_is_not_owned_when_lsof_cannot_answer(monkeypatch, error) -> None:
    launcher = _load(monkeypatch)
    def run(argv, **kwargs):
        raise error
    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.owns_port(4242, "5000") is False


def test_serve_flag_runs_the_server_and_never_opens_a_window(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setattr(launcher, "serve", lambda port: port)
    monkeypatch.setattr(launcher, "run_window", lambda: pytest.fail("a served child must not open a window"))
    monkeypatch.setattr(sys, "argv", ["Grant Matcher", "--serve", "51234"])
    assert launcher.main() == 51234


def test_server_runs_from_the_data_folder(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    seen: dict = {}
    def fake_main() -> int:
        seen.update(cwd=Path.cwd(), argv=list(sys.argv))
        return 0
    web = types.ModuleType("streamlit.web")
    web.cli = types.SimpleNamespace(main=fake_main)
    monkeypatch.setitem(sys.modules, "streamlit", types.ModuleType("streamlit"))
    monkeypatch.setitem(sys.modules, "streamlit.web", web)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # The watchdog exits the process when its parent is PID 1, which is how pytest can run in a container.
    monkeypatch.setattr(launcher.threading, "Thread", lambda **kwargs: types.SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.chdir(tmp_path)
    assert launcher.serve(51234) == 0
    assert seen["cwd"].resolve() == launcher.data_dir(tmp_path).resolve() and "--server.port=51234" in seen["argv"]


def test_no_updater_when_the_app_is_not_frozen(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    assert launcher.sparkle_framework() is None and launcher.app_menu() == []


def test_updater_framework_is_found_inside_the_frozen_bundle(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    framework = tmp_path / "Grant Matcher.app" / "Contents" / "Frameworks" / "Sparkle.framework"
    framework.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Grant Matcher.app" / "Contents" / "MacOS" / "Grant Matcher"))
    assert launcher.sparkle_framework() == framework


def test_frozen_bundle_without_sparkle_has_no_updater(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Contents" / "MacOS" / "Grant Matcher"))
    assert launcher.sparkle_framework() is None


def test_a_failed_updater_start_is_logged_and_never_raised(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setitem(sys.modules, "objc", None)
    log = tmp_path / "server.log"
    launcher.start_updater(tmp_path / "Sparkle.framework", log)
    assert launcher.UPDATER == [] and "updater did not start" in log.read_text()


def test_checking_for_updates_without_an_updater_tells_the_user(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    shown = []
    monkeypatch.setattr(launcher, "alert", shown.append)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    launcher.check_for_updates()
    assert len(shown) == 1 and "cannot check for updates" in shown[0] and str(launcher.log_path(tmp_path)) in shown[0]


def _fake_objc(monkeypatch) -> list:
    calls = []
    objc = types.ModuleType("objc")
    objc.loadBundle = lambda name, namespace, bundle_path: calls.append(("load", bundle_path))
    made = types.SimpleNamespace(initWithStartingUpdater_updaterDelegate_userDriverDelegate_=lambda *args: calls.append(("init", args)))
    objc.lookUpClass = lambda name: calls.append(("class", name)) or types.SimpleNamespace(alloc=lambda: made)
    monkeypatch.setitem(sys.modules, "objc", objc)
    return calls


def test_check_updater_flag_loads_sparkle_and_never_opens_a_window(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    calls = _fake_objc(monkeypatch)
    monkeypatch.setattr(launcher, "sparkle_framework", lambda: tmp_path / "Sparkle.framework")
    monkeypatch.setattr(launcher, "run_window", lambda: pytest.fail("the check must not open a window"))
    monkeypatch.setattr(sys, "argv", ["Grant Matcher", "--check-updater"])
    assert launcher.main() == 0
    assert calls[:2] == [("load", str(tmp_path / "Sparkle.framework")), ("class", "SPUStandardUpdaterController")]
    # The check builds the controller without starting it, because that is the call that fails at launch.
    assert calls[2:] == [("init", (False, None, None))]


def test_check_updater_flag_fails_when_sparkle_cannot_load(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setitem(sys.modules, "objc", None)
    monkeypatch.setattr(launcher, "sparkle_framework", lambda: tmp_path / "Sparkle.framework")
    monkeypatch.setattr(launcher, "run_window", lambda: pytest.fail("the check must not open a window"))
    monkeypatch.setattr(sys, "argv", ["Grant Matcher", "--check-updater"])
    with pytest.raises(ImportError):
        launcher.main()


def test_updater_starts_even_when_the_server_does_not(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    scheduled = []
    tools = types.ModuleType("PyObjCTools")
    tools.AppHelper = types.SimpleNamespace(callAfter=lambda function, *args: scheduled.append((function, args)))
    monkeypatch.setitem(sys.modules, "PyObjCTools", tools)
    framework, log = tmp_path / "Sparkle.framework", tmp_path / "server.log"
    monkeypatch.setattr(launcher, "sparkle_framework", lambda: framework)
    # The answer records what was scheduled when the wait for the server began.
    monkeypatch.setattr(launcher, "start_failure", lambda child, url: f"seen {len(scheduled)}")
    window = _Window()
    launcher.wait_and_load(window, _Child(), "http://127.0.0.1:9", log)
    assert scheduled == [(launcher.start_updater, (framework, log))] and "seen 1" in window.shown[0][1]


def test_window_still_loads_when_the_updater_cannot_be_scheduled(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setitem(sys.modules, "PyObjCTools", None)
    monkeypatch.setattr(launcher, "sparkle_framework", lambda: tmp_path / "Sparkle.framework")
    _lsof_reports(monkeypatch, launcher, "4242\n")
    window, url, log = _Window(), _healthy_server_url(), tmp_path / "server.log"
    launcher.wait_and_load(window, _Child(), url, log)
    assert window.shown == [("url", url)] and "updater did not start" in log.read_text()


def test_frozen_app_without_sparkle_says_so_in_the_log(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Contents" / "MacOS" / "Grant Matcher"))
    _lsof_reports(monkeypatch, launcher, "4242\n")
    window, url, log = _Window(), _healthy_server_url(), tmp_path / "server.log"
    launcher.wait_and_load(window, _Child(), url, log)
    assert window.shown == [("url", url)] and "Sparkle.framework is missing" in log.read_text()


def test_started_updater_is_kept_and_the_menu_item_reaches_it(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    checks = []
    controller = types.SimpleNamespace(checkForUpdates_=checks.append)
    made = types.SimpleNamespace(initWithStartingUpdater_updaterDelegate_userDriverDelegate_=lambda start, a, b: controller if (start, a, b) == (True, None, None) else None)
    monkeypatch.setattr(launcher, "sparkle_class", lambda framework: types.SimpleNamespace(alloc=lambda: made))
    tools = types.ModuleType("PyObjCTools")
    tools.AppHelper = types.SimpleNamespace(callAfter=lambda function, *args: function(*args))
    monkeypatch.setitem(sys.modules, "PyObjCTools", tools)
    monkeypatch.setattr(launcher, "alert", lambda message: pytest.fail(message))
    launcher.start_updater(tmp_path / "Sparkle.framework", tmp_path / "server.log")
    launcher.check_for_updates()
    assert launcher.UPDATER == [controller] and checks == [None]


def test_the_server_does_not_overwrite_what_the_app_writes_to_the_log(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log = launcher.log_path(tmp_path)
    real_popen = subprocess.Popen
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, **kwargs: real_popen([sys.executable, "-c", "import time; time.sleep(0.5); print('server line ' * 20, flush=True)"], **kwargs))
    def start(function, args, menu) -> None:
        with log.open("a") as out:
            out.write("Grant Matcher updater did not start:\n")
        args[1].wait()
    webview = types.ModuleType("webview")
    webview.settings, webview.create_window, webview.start = {}, lambda *args, **kwargs: None, start
    monkeypatch.setitem(sys.modules, "webview", webview)
    launcher.run_window()
    assert "updater did not start" in log.read_text() and "server line" in log.read_text()

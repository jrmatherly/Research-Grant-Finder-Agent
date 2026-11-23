import multiprocessing, os, socket, subprocess, sys, threading, time, urllib.request
from html import escape
from pathlib import Path

NAME = "Grant Matcher"


def data_dir(home: Path) -> Path:
    return home / "Library" / "Application Support" / NAME


def log_path(home: Path) -> Path:
    return home / "Library" / "Logs" / NAME / "server.log"


def app_script() -> Path:
    return Path(sys._MEIPASS) / "streamlit_app.py" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent / "streamlit_app.py"


def server_argv(app: Path, port: int) -> list[str]:
    return ["streamlit", "run", str(app), "--global.developmentMode=false", "--server.address=127.0.0.1", "--server.allowedHosts=127.0.0.1", "--server.headless=true", f"--server.port={port}", "--browser.gatherUsageStats=false", "--server.showEmailPrompt=false", "--client.toolbarMode=viewer", "--server.fileWatcherType=none"]


def page(text: str) -> str:
    return f"<html><body style='font:15px -apple-system,sans-serif;display:grid;place-items:center;height:90vh;color:#444'><p>{escape(text)}</p></body></html>"


def serve(port: int) -> int:
    home = data_dir(Path.home())
    home.mkdir(parents=True, exist_ok=True)
    os.chdir(home)

    def watch() -> None:
        # Quit kills only the window process, so the server exits once it is orphaned to launchd.
        while os.getppid() != 1: time.sleep(1)
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()
    from streamlit.web import cli
    sys.argv = server_argv(app_script(), port)
    return cli.main()


def owns_port(pid: int, port: str) -> bool:
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return str(pid) in out.split()


def wait_and_load(window, child: subprocess.Popen, url: str, log: Path) -> None:
    # A system or environment proxy must not carry the request to our own loopback server.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and child.poll() is None:
        try:
            opener.open(url + "/_stcore/health", timeout=1)
        except OSError:
            time.sleep(0.25)
            continue
        # Another local process can take the port between the parent choosing it and the server binding it, so load the page only from our own child.
        if owns_port(child.pid, url.rsplit(":", 1)[1]):
            return window.load_url(url)
        break
    child.terminate()
    window.load_html(page(f"{NAME} could not start its server. See the log at {log}."))


def main() -> int:
    multiprocessing.freeze_support()
    if "--serve" in sys.argv:
        return serve(int(sys.argv[sys.argv.index("--serve") + 1]))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    log = log_path(Path.home())
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "--serve", str(port)] if getattr(sys, "frozen", False) else [sys.executable, __file__, "--serve", str(port)]
    with log.open("wb") as out:
        child = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
        window = webview.create_window(NAME, html=page(f"Starting {NAME}…"), width=1400, height=900, text_select=True)
        webview.start(wait_and_load, (window, child, f"http://127.0.0.1:{port}", log))
    finally:
        child.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

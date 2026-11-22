from nih_grant_matcher.clients import GrantsGovClient


class FakeGrantsGovClient(GrantsGovClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []
    def search(self, agencies, statuses, rows=50, keyword="", start_record=0):
        self.calls.append((rows, start_record))
        if start_record == 0:
            return [{"id": i} for i in range(rows)]
        if start_record == rows:
            return [{"id": rows + i} for i in range(25)]
        return []


def test_grantsgov_search_all_paginates() -> None:
    client = FakeGrantsGovClient()
    hits = client.search_all(["HHS-NIH11"], ["posted"], limit=125)
    assert len(hits) == 125
    assert client.calls == [(100, 0), (100, 100)]


def test_read_retries_a_dropped_connection(monkeypatch) -> None:
    import socket, threading, urllib.request
    from nih_grant_matcher import clients
    server = socket.create_server(("127.0.0.1", 0))
    def serve() -> None:
        # The first connection closes with no reply, as a dropped connection does. The second answers.
        first, _ = server.accept()
        first.recv(65536)
        first.close()
        second, _ = server.accept()
        second.recv(65536)
        second.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        second.close()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    try:
        assert clients._read(urllib.request.Request(f"http://127.0.0.1:{server.getsockname()[1]}/"), timeout=5) == b"ok"
    finally:
        thread.join(timeout=5)
        server.close()

def test_read_does_not_retry_a_client_error(monkeypatch) -> None:
    import urllib.error
    import pytest
    from nih_grant_matcher import clients
    calls = []
    def fake_urlopen(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError("u", 404, "missing", None, None)
    monkeypatch.setattr(clients.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        clients._read("request", timeout=1)
    assert len(calls) == 1

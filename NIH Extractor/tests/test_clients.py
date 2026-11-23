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


import socket, ssl, threading, urllib.error, urllib.request

import pytest

from nih_grant_matcher import clients

REQUEST = urllib.request.Request("https://example.invalid/data")


def _fail_then(monkeypatch, outcomes: list) -> list:
    calls = []
    def fake_urlopen(request, timeout):
        calls.append(request)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(clients.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    return calls


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(REQUEST.full_url, code, "error", None, None)


def test_read_retries_a_dropped_connection(monkeypatch) -> None:
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
    # A proxy set in the environment would otherwise receive this loopback request.
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    try:
        assert clients._read(urllib.request.Request(f"http://127.0.0.1:{server.getsockname()[1]}/"), timeout=5) == b"ok"
    finally:
        thread.join(timeout=5)
        server.close()


@pytest.mark.parametrize("failure", [_http_error(503), _http_error(429), TimeoutError("timed out"), urllib.error.URLError("reset")], ids=["503", "429", "timeout", "urlerror"])
def test_read_retries_a_failure_that_can_pass(monkeypatch, failure) -> None:
    import io
    calls = _fail_then(monkeypatch, [failure, io.BytesIO(b"ok")])
    assert clients._read(REQUEST, timeout=1) == b"ok"
    assert len(calls) == 2


def test_read_gives_up_after_three_attempts_and_names_the_address(monkeypatch) -> None:
    calls = _fail_then(monkeypatch, [_http_error(503)] * 5)
    with pytest.raises(clients.ApiError, match=r"https://example\.invalid/data failed after 3 attempt\(s\): HTTP Error 503"):
        clients._read(REQUEST, timeout=1)
    assert len(calls) == 3


def test_read_does_not_retry_a_client_error(monkeypatch) -> None:
    calls = _fail_then(monkeypatch, [_http_error(404)] * 3)
    with pytest.raises(clients.ApiError, match="failed after 1 attempt"):
        clients._read(REQUEST, timeout=1)
    assert len(calls) == 1


@pytest.mark.parametrize("wrapped", [True, False], ids=["in-urlerror", "bare"])
def test_read_does_not_retry_a_certificate_error(monkeypatch, wrapped) -> None:
    certificate = ssl.SSLCertVerificationError("unable to get local issuer certificate")
    calls = _fail_then(monkeypatch, [urllib.error.URLError(certificate) if wrapped else certificate] * 3)
    with pytest.raises((urllib.error.URLError, ssl.SSLCertVerificationError)):
        clients._read(REQUEST, timeout=1)
    assert len(calls) == 1


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
def test_read_reports_a_certificate_error_once_without_a_retry(monkeypatch, wrapped) -> None:
    certificate = ssl.SSLCertVerificationError("unable to get local issuer certificate")
    calls = _fail_then(monkeypatch, [urllib.error.URLError(certificate) if wrapped else certificate] * 3)
    with pytest.raises(clients.ApiError, match=r"https://example\.invalid/data failed after 1 attempt\(s\): .*unable to get local issuer certificate"):
        clients._read(REQUEST, timeout=1)
    assert len(calls) == 1
    # The error says what to do, because the usual cause is a proxy that the user can configure.
    with pytest.raises(clients.ApiError, match="SSL_CERT_FILE"):
        clients._read(REQUEST, timeout=1)


def test_a_failed_request_names_the_address_without_its_query(monkeypatch) -> None:
    _fail_then(monkeypatch, [_http_error(404)])
    with pytest.raises(clients.ApiError) as raised:
        clients._read(urllib.request.Request("https://example.invalid/data?perpage=100&sort=reldate"), timeout=1)
    assert str(raised.value).startswith("https://example.invalid/data failed after 1 attempt(s)")


@pytest.mark.parametrize("body, reason", [(b"<html>blocked</html>", r"did not return JSON\. The reply starts with b'<html>blocked"), (b"\xff<html>", "did not return JSON"), (b"[]", "returned JSON that is not an object"), (b"null", "returned JSON that is not an object")], ids=["html", "not-utf8", "list", "null"])
def test_a_reply_that_is_not_a_json_object_is_an_api_error(monkeypatch, body, reason) -> None:
    monkeypatch.setattr(clients, "_read", lambda request, timeout, attempts=3: body)
    with pytest.raises(clients.ApiError, match=r"https://example\.invalid/search " + reason):
        clients._post_json("https://example.invalid/search", {})
    with pytest.raises(clients.ApiError, match=reason):
        clients.NihGuideClient().search(rows=1)


def test_nih_guide_default_run_reads_every_page(monkeypatch) -> None:
    import json, urllib.parse
    from nih_grant_matcher.agents import NihGuideIngestionAgent
    from nih_grant_matcher.config import MatcherConfig
    offsets = []
    def fake_read(request, timeout, attempts=3):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        start, size = int(query["from"][0]), int(query["perpage"][0])
        offsets.append((start, size))
        hits = [{"_source": {"rowid": str(n), "docnum": f"PAR-27-{n:03d}", "title": "Notice", "type": "active"}} for n in range(start, min(start + size, 371))]
        return json.dumps({"data": {"hits": {"hits": hits}}}).encode()
    monkeypatch.setattr(clients, "_read", fake_read)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    opportunities = NihGuideIngestionAgent(clients.NihGuideClient(), MatcherConfig()).ingest()
    assert len({opportunity.source_id for opportunity in opportunities}) == 371
    assert offsets == [(0, 100), (100, 100), (200, 100), (300, 100)]


@pytest.mark.parametrize("docnum, expected", [("PAR-27-090", ("Body", "360675")), ("PAR-27-091", ("", ""))], ids=["same", "other"])
def test_doctext_takes_the_text_only_of_the_document_asked_for(monkeypatch, docnum, expected) -> None:
    import json, urllib.parse
    from nih_grant_matcher.config import NIH_GUIDE_DOCTEXT_URL
    def fake_read(request, timeout, attempts=3):
        url, _, query = request.full_url.partition("?")
        assert url == NIH_GUIDE_DOCTEXT_URL and urllib.parse.parse_qs(query)["query"] == ["PAR-27-090"] and urllib.parse.parse_qs(query)["perpage"] == ["5"]
        return json.dumps({"data": {"hits": {"hits": [{"_source": {"docnum": docnum, "doctext": "Body", "ggid": "360675"}}]}}}).encode()
    monkeypatch.setattr(clients, "_read", fake_read)
    assert clients.NihGuideClient().doctext("PAR-27-090") == expected


@pytest.mark.parametrize("file_name, expected", [("PAR-27-090-Full-Announcement.html", "<p>Full</p>"), ("PAR-27-090-Notice.pdf", "")], ids=["full", "none"])
def test_full_announcement_downloads_only_the_full_announcement_attachment(monkeypatch, file_name, expected) -> None:
    import json
    from nih_grant_matcher.config import GRANTSGOV_ATTACHMENT_URL, GRANTSGOV_FETCH_URL
    reads = []
    def fake_read(request, timeout, attempts=3):
        reads.append(request.full_url)
        if request.full_url == GRANTSGOV_FETCH_URL:
            return json.dumps({"errorcode": 0, "data": {"synopsisAttachmentFolders": [{"synopsisAttachments": [{"id": 355218, "fileName": file_name}]}]}}).encode()
        return b"<p>Full</p>"
    monkeypatch.setattr(clients, "_read", fake_read)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    assert clients.GrantsGovClient().full_announcement("360675") == expected
    assert reads[1:] == ([f"{GRANTSGOV_ATTACHMENT_URL}/355218"] if expected else [])


@pytest.mark.parametrize("attachment", [{"fileName": "PAR-27-090-Full-Announcement.html"}, {"id": "../x", "fileName": "PAR-27-090-Full-Announcement.html"}, {"id": "1?a=b", "fileName": "PAR-27-090-Full-Announcement.html"}], ids=["no-id", "path", "query"])
def test_a_full_announcement_without_a_numeric_id_is_an_api_error_and_is_not_requested(monkeypatch, attachment) -> None:
    import json
    from nih_grant_matcher.config import GRANTSGOV_FETCH_URL
    reads = []
    def fake_read(request, timeout, attempts=3):
        reads.append(request.full_url)
        return json.dumps({"errorcode": 0, "data": {"synopsisAttachmentFolders": [{"synopsisAttachments": [attachment]}]}}).encode()
    monkeypatch.setattr(clients, "_read", fake_read)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    with pytest.raises(clients.ApiError, match="attachment id"):
        clients.GrantsGovClient().full_announcement("360675")
    assert reads == [GRANTSGOV_FETCH_URL]


def test_doctext_takes_the_hit_for_the_number_when_another_document_ranks_first(monkeypatch) -> None:
    import json
    hits = [{"_source": {"docnum": "NOT-OD-27-001", "doctext": "A notice that cites PAR-27-090.", "ggid": "1"}}, {"_source": {"docnum": "PAR-27-090", "doctext": "Body", "ggid": "360675"}}]
    monkeypatch.setattr(clients, "_read", lambda request, timeout, attempts=3: json.dumps({"data": {"hits": {"hits": hits}}}).encode())
    assert clients.NihGuideClient().doctext("PAR-27-090") == ("Body", "360675")

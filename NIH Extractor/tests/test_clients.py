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


# PAR-26-121 on Grants.gov on 2026-11-23 has the first announcement and its revision, in that order.
@pytest.mark.parametrize("dates, expected", [(("Dec 11, 2025 12:55:49 PM EST", "Dec 18, 2025 02:19:42 PM EST", "Dec 16, 2025 09:00:00 AM EST"), 2), (("Dec 18, 2025 02:19:42 PM EST", "Dec 11, 2025 12:55:49 PM EST", "Dec 16, 2025 09:00:00 AM EST"), 1), (("Dec 18, 2025 02:19:42 PM EST", "soon", "Dec 11, 2025 12:55:49 PM EST"), 1), (("soon", None, "later"), 3), (("Dec 18, 2025 02:19:42 PM EST", "Dec 18, 2025 02:19:42 PM EST"), 2), (("Dec 11, 2025 12:55:49 PM ET", "Dec 18, 2025 02:19:42 PM AKST", "Dec 16, 2025 09:00:00 AM ET"), 2)], ids=["newest-second", "newest-first", "an-unreadable-date-is-the-oldest", "no-readable-date-takes-the-last", "a-tie-takes-the-later-in-the-list", "a-zone-of-another-length"])
def test_full_announcement_downloads_the_newest_full_announcement(monkeypatch, dates, expected) -> None:
    import json
    from nih_grant_matcher.config import GRANTSGOV_ATTACHMENT_URL, GRANTSGOV_FETCH_URL
    reads = []
    def fake_read(request, timeout, attempts=3):
        reads.append(request.full_url)
        if request.full_url == GRANTSGOV_FETCH_URL:
            return json.dumps({"errorcode": 0, "data": {"synopsisAttachmentFolders": [{"synopsisAttachments": [{"id": n, "fileName": f"PAR-26-121-{n}-Full-Announcement.html", "createdDate": d}, {"id": 9, "fileName": "PAR-26-121.pdf", "createdDate": "Dec 31, 2025 09:00:00 AM EST"}]} for n, d in enumerate(dates, 1)]}}).encode()
        return b"<p>Full</p>"
    monkeypatch.setattr(clients, "_read", fake_read)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    assert clients.GrantsGovClient().full_announcement("359862") == "<p>Full</p>" and reads[1:] == [f"{GRANTSGOV_ATTACHMENT_URL}/{expected}"]


@pytest.mark.parametrize("attachment", [{"fileName": "PAR-27-090-Full-Announcement.html"},{"id": "../x", "fileName": "PAR-27-090-Full-Announcement.html"}, {"id": "1?a=b", "fileName": "PAR-27-090-Full-Announcement.html"}], ids=["no-id", "path", "query"])
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


@pytest.mark.parametrize("folders", [5, [{"synopsisAttachments": 5}]], ids=["folders", "attachments"])
def test_an_attachment_list_that_is_not_a_list_is_an_api_error(monkeypatch, folders) -> None:
    import json
    monkeypatch.setattr(clients, "_read", lambda request, timeout, attempts=3: json.dumps({"errorcode": 0, "data": {"synopsisAttachmentFolders": folders}}).encode())
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    with pytest.raises(clients.ApiError, match="not a list"):
        clients.GrantsGovClient().full_announcement("360675")


def test_doctext_takes_the_hit_for_the_number_when_another_document_ranks_first(monkeypatch) -> None:
    import json
    hits = [{"_source": {"docnum": "NOT-OD-27-001", "doctext": "A notice that cites PAR-27-090.", "ggid": "1"}}, {"_source": {"docnum": "PAR-27-090", "doctext": "Body", "ggid": "360675"}}]
    monkeypatch.setattr(clients, "_read", lambda request, timeout, attempts=3: json.dumps({"data": {"hits": {"hits": hits}}}).encode())
    assert clients.NihGuideClient().doctext("PAR-27-090") == ("Body", "360675")


def _replies(monkeypatch, *outcomes) -> list:
    import io, json
    return _fail_then(monkeypatch, [o if isinstance(o, Exception) else io.BytesIO(json.dumps(o).encode()) for o in outcomes])


def test_a_pmid_gives_the_title_pubmed_holds_and_sends_no_address(monkeypatch) -> None:
    calls = _replies(monkeypatch, {"result": {"uids": ["33611339"], "33611339": {"uid": "33611339", "title": "The role of m6A\n\x1b modification. "}}})
    assert clients.ReferenceClient().lookup(pmid="33611339", doi="10.1/ignored") == "The role of m6A modification."
    url = calls[0].full_url
    assert url.startswith("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?") and "db=pubmed" in url and "id=33611339" in url and "tool=nih-grant-matcher" in url
    assert "email" not in url and "mailto" not in url and calls[0].get_header("User-agent") == "nih-grant-matcher/0.1"


@pytest.mark.parametrize("reply", [{"result": {"uids": ["999999999"], "999999999": {"uid": "999999999", "error": "cannot get document summary"}}}, {"error": "Invalid uid 999999999 at position= 0", "result": {"uids": []}}], ids=["no-record", "invalid-uid"])
def test_a_pmid_pubmed_does_not_hold_gives_an_empty_title(monkeypatch, reply) -> None:
    _replies(monkeypatch, reply)
    assert clients.ReferenceClient().lookup(pmid="999999999") == ""


def test_a_doi_gives_the_joined_crossref_title_and_cannot_add_a_query(monkeypatch) -> None:
    calls = _replies(monkeypatch, {"status": "ok", "message": {"title": ["Highly accurate", "protein structure prediction"]}})
    assert clients.ReferenceClient().lookup(doi="10.1038/s41586?x=1") == "Highly accurate protein structure prediction"
    assert calls[0].full_url == "https://api.crossref.org/works/10.1038/s41586%3Fx%3D1" and "mailto" not in calls[0].full_url


def test_a_doi_crossref_does_not_hold_gives_an_empty_title(monkeypatch) -> None:
    calls = _replies(monkeypatch, _http_error(404))
    assert clients.ReferenceClient().lookup(doi="10.9999/does.not.exist") == ""
    assert len(calls) == 1


def test_a_record_with_no_title_is_not_reported_as_missing(monkeypatch) -> None:
    _replies(monkeypatch, {"message": {"title": []}})
    assert clients.ReferenceClient().lookup(doi="10.1/x") == clients.UNTITLED


@pytest.mark.parametrize("outcomes", [[_http_error(429)] * 3, [_http_error(503)] * 3, [{"error": "API rate limit exceeded", "count": "11"}], [{"result": {"uids": []}}]], ids=["429", "503", "rate-limit", "shape"])
def test_a_reply_that_is_not_an_answer_is_an_api_error_naming_the_service(monkeypatch, outcomes) -> None:
    _replies(monkeypatch, *outcomes)
    with pytest.raises(clients.ApiError, match="PubMed"):
        clients.ReferenceClient().lookup(pmid="1")


def test_lookups_pause_under_three_requests_a_second(monkeypatch) -> None:
    _replies(monkeypatch, {"message": {"title": ["A"]}}, {"message": {"title": ["B"]}})
    slept = []
    monkeypatch.setattr(clients.time, "sleep", slept.append)
    client = clients.ReferenceClient()
    client.lookup(doi="10.1/a"), client.lookup(doi="10.1/b")
    assert len(slept) == 2 and min(slept) >= 1 / 3


@pytest.mark.parametrize("outcomes", [[_http_error(503)] * 3, [TimeoutError("timed out")] * 3], ids=["503", "timeout"])
def test_a_crossref_that_does_not_answer_is_an_api_error_naming_crossref(monkeypatch, outcomes) -> None:
    _replies(monkeypatch, *outcomes)
    with pytest.raises(clients.ApiError, match="with Crossref failed"):
        clients.ReferenceClient().lookup(doi="10.1/x")


def test_a_lookup_waits_ten_seconds_for_an_answer(monkeypatch) -> None:
    import io, json
    waited = []
    monkeypatch.setattr(clients.urllib.request, "urlopen", lambda request, timeout: waited.append(timeout) or io.BytesIO(json.dumps({"message": {"title": ["A"]}}).encode()))
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    clients.ReferenceClient().lookup(doi="10.1/a")
    assert waited == [10]

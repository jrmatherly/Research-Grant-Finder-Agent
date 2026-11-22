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
    import io, urllib.error
    from nih_grant_matcher import clients
    responses = [urllib.error.URLError("reset"), urllib.error.HTTPError("u", 503, "busy", None, None), io.BytesIO(b"ok")]
    def fake_urlopen(request, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(clients.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)
    assert clients._read("request", timeout=1) == b"ok"
    assert responses == []

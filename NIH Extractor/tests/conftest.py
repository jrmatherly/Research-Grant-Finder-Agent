import io, json, urllib.error
import pytest
from nih_grant_matcher import llm

class Post:
    def __init__(self) -> None: self.queue, self.slept, self.calls, self.url, self.headers, self.body = [], [], 0, "", {}, None
    def reply(self, data: dict) -> None: self.queue.append(lambda url: io.BytesIO(json.dumps(data).encode()))
    def fail(self, status: int, data: dict, headers: dict | None = None) -> None:
        def failed(url: str):
            raise urllib.error.HTTPError(url, status, "", headers or {}, io.BytesIO(json.dumps(data).encode()))
        self.queue.append(failed)
    def fail_with(self, exc: BaseException) -> None:
        def failed(url: str):
            raise exc
        self.queue.append(failed)
    def __call__(self, request, timeout=None):
        self.calls += 1
        self.url, self.headers, self.body = request.full_url, dict(request.headers), json.loads(request.data) if request.data else None
        return self.queue.pop(0)(request.full_url)

@pytest.fixture
def post(monkeypatch) -> Post:
    fake = Post()
    monkeypatch.setattr(llm, "_open", fake)
    monkeypatch.setattr(llm, "_sleep", fake.slept.append)
    return fake

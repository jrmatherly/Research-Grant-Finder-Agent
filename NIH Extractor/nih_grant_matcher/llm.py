from __future__ import annotations
import http.client, json, re, time, urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Literal
from . import keys
from .clients import ApiError
from .models import Completion, Model
from .store import OpportunityStore

# shortcut: no streaming, so a long reply shows a spinner. Add streaming when a section takes longer than the 600 second timeout.
_open = urllib.request.urlopen
_sleep = time.sleep
ANTHROPIC_VERSION = "2026-10-21"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
Kind = Literal["auth", "rate", "quota", "overload", "refused", "other"]

@dataclass(frozen=True)
class Provider:
    name: str
    wire: Literal["anthropic", "openai", "gemini"]
    base_url: str
    key_env: str
    needs_key: bool = True
    default_model: str = ""

PROVIDERS = {p.name: p for p in (
    Provider("claude", "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", default_model="claude-opus-5-5"),
    Provider("openai", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    Provider("gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta", "GEMINI_API_KEY"),
    Provider("compatible", "openai", "http://localhost:11434/v1", "GRANT_MATCHER_LLM_KEY", needs_key=False))}

class ModelError(ApiError):
    def __init__(self, message: str, kind: Kind = "other", status: int = 0, wait: float = 2.0) -> None:
        super().__init__(message)
        self.kind, self.status, self.wait = kind, status, wait

def host_of(base_url: str) -> str:
    return urllib.parse.urlsplit(base_url).hostname or ""

def checked_base_url(base_url: str) -> str:
    base_url = base_url.strip()
    if urllib.parse.urlsplit(base_url).scheme not in ("http", "https") or not host_of(base_url):
        raise ValueError(f"{base_url!r} is not a server address. Write it as http://host:port/v1 or https://host/v1.")
    return base_url

def _redact(text: str, key: str | None) -> str:
    # A provider can echo the key, or its last four characters after "...", in an error.
    return text.replace(key, "[key]").replace(f"...{key[-4:]}", "...[key]") if key else text

def _send(url: str, headers: dict[str, str], body: dict | None, key: str | None, timeout: int = 600) -> dict:
    # One attempt. clients._read retries any failure three times, which would pay for a reply three times.
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "nih-grant-matcher/0.1", **headers}, method="GET" if body is None else "POST")
    host = host_of(url)
    try:
        with _open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, host, key) from None
    except (OSError, http.client.HTTPException) as exc:
        raise ModelError(_redact(f"{host} did not answer: {exc}. The request may have reached {host}, so it may be charged. It was not sent again.", key)) from None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ModelError(f"{host} did not return JSON. The reply starts with {raw[:80]!r}") from None
    if not isinstance(parsed, dict):
        raise ModelError(f"{host} returned JSON that is not an object")
    return parsed

def _http_error(exc: urllib.error.HTTPError, host: str, key: str | None) -> ModelError:
    raw = (exc.read(2000) if exc.fp else b"").decode("utf-8", errors="replace")
    try:
        error = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        error = None
    error = error if isinstance(error, dict) else {}
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    names = " ".join(str(v) for v in (error.get("type"), error.get("code"), error.get("status"), details.get("error_code")) if v)
    status = exc.code
    kind: Kind = "auth" if status in (401, 403) else "quota" if status == 402 or status == 429 and re.search(r"quota|credit|spend|usage_limit", names, re.I) else "rate" if status == 429 else "overload" if status in (500, 503, 529) else "other"
    try:
        wait = min(float((exc.headers or {}).get("retry-after") or 2), 30.0)
    except ValueError:
        wait = 2.0
    message = str(error.get("message") or raw.strip()[:300] or exc.reason)
    return ModelError(_redact(f"{host} answered {status}: {message}", key), kind, status, wait)

def _retry(send: Callable[[], dict]) -> dict:
    try:
        return send()
    except ModelError as exc:
        # Only these statuses say the provider did not process the request. A 500 may have been charged.
        if exc.status not in (429, 503, 529) or exc.kind == "quota":
            raise
        _sleep(exc.wait)
    return send()

def _bearer(key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}

class HttpModel:
    def __init__(self, provider: Provider, name: str, base_url: str, key: str | None) -> None:
        self.provider, self.name, self.base_url, self.host, self.wire = provider.name, name, base_url.rstrip("/"), host_of(base_url), provider.wire
        self._key = key
        # Ollama's page lists max_tokens, and OpenAI calls it deprecated in favour of max_completion_tokens.
        self._limit = "max_tokens" if provider.name == "compatible" else "max_completion_tokens"
    def complete(self, system: str, user: str, max_tokens: int = 16000) -> Completion:
        build, read = _WIRES[self.wire]
        url, headers, body = build(self, system, user, max_tokens)
        try:
            data = _retry(lambda: _send(url, headers, body, self._key))
        except ModelError as exc:
            if not (self.wire == "openai" and exc.status == 400 and self._limit in str(exc)):
                raise
            # The server named the token limit it was sent, so it did not process the request.
            other = "max_tokens" if self._limit == "max_completion_tokens" else "max_completion_tokens"
            body = {**{k: v for k, v in body.items() if k != self._limit}, other: max_tokens}
            data = _retry(lambda: _send(url, headers, body, self._key))
        try:
            return read(self, data)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ModelError(f"The reply from {self.host} was not in the form Grant Matcher reads: {exc!r}") from None

def _anthropic_request(m: HttpModel, system: str, user: str, max_tokens: int) -> tuple[str, dict[str, str], dict[str, Any]]:
    # fallbacks sends a request that a safety classifier declines on to the model Anthropic recommends, so a declined biology grant can still get an answer.
    return f"{m.base_url}/messages", {**_bearer(m._key), "anthropic-version": ANTHROPIC_VERSION, "anthropic-beta": FALLBACK_BETA}, {"model": m.name, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}], "fallbacks": "default"}

def _anthropic_reply(m: HttpModel, data: dict) -> Completion:
    if data["stop_reason"] == "refusal":
        details = data.get("stop_details") or {}
        raise ModelError(f"{m.host} declined the request ({details.get('category') or 'no category'}). {details.get('explanation') or ''}".strip(), "refused")
    text = "".join(block["text"] for block in data["content"] if block.get("type") == "text")
    return Completion(text, data.get("model") or m.name, data["usage"]["input_tokens"], data["usage"]["output_tokens"], data["stop_reason"] in ("max_tokens", "model_context_window_exceeded"))

def _openai_request(m: HttpModel, system: str, user: str, max_tokens: int) -> tuple[str, dict[str, str], dict[str, Any]]:
    return f"{m.base_url}/chat/completions", _bearer(m._key), {"model": m.name, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], m._limit: max_tokens}

def _openai_reply(m: HttpModel, data: dict) -> Completion:
    choice = data["choices"][0]
    message, usage = choice["message"], data.get("usage") or {}
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        raise ModelError(f"{m.host} declined the request. {message.get('refusal') or 'Its content filter omitted the reply.'}", "refused")
    return Completion(message.get("content") or "", data.get("model") or m.name, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), choice.get("finish_reason") == "length")

def _gemini_request(m: HttpModel, system: str, user: str, max_tokens: int) -> tuple[str, dict[str, str], dict[str, Any]]:
    # Without store false, Google keeps the request and the reply for 1 to 55 days.
    return f"{m.base_url}/interactions", {"x-goog-api-key": m._key} if m._key else {}, {"model": m.name, "system_instruction": system, "input": user, "generation_config": {"max_output_tokens": max_tokens}, "store": False}

def _gemini_reply(m: HttpModel, data: dict) -> Completion:
    if data["status"] not in ("completed", "incomplete"):
        raise ModelError(f"{m.host} ended the request with the status {data['status']}.")
    text = "".join(c["text"] for step in data["steps"] if step.get("type") == "model_output" for c in step.get("content") or [] if c.get("type") == "text")
    usage = data.get("usage") or {}
    return Completion(text, data.get("model") or m.name, usage.get("total_input_tokens", 0), usage.get("total_output_tokens", 0), data["status"] == "incomplete")

_WIRES = {"anthropic": (_anthropic_request, _anthropic_reply), "openai": (_openai_request, _openai_reply), "gemini": (_gemini_request, _gemini_reply)}

def list_models(provider: Provider, base_url: str, key: str | None) -> list[str]:
    base = base_url.rstrip("/")
    try:
        if provider.wire == "anthropic":
            return [m["id"] for m in _send(f"{base}/models?limit=1000", {**_bearer(key), "anthropic-version": ANTHROPIC_VERSION}, None, key, 30)["data"]]
        if provider.wire == "gemini":
            return [m["name"].removeprefix("models/") for m in _send(f"{base}/models?pageSize=1000", {"x-goog-api-key": key} if key else {}, None, key, 30)["models"] if "generateContent" in m.get("supportedGenerationMethods", [])]
        return [m["id"] for m in _send(f"{base}/models", _bearer(key), None, key, 30)["data"]]
    except (KeyError, TypeError) as exc:
        raise ModelError(f"The model list from {host_of(base_url)} was not in the form Grant Matcher reads: {exc!r}") from None

def cautions(provider: Provider, base_url: str) -> list[str]:
    said = ["A free-tier Gemini key lets Google use what you send to improve its products. Use a paid key for unpublished work."] if provider.name == "gemini" else []
    if base_url.startswith("http://") and host_of(base_url) not in LOCAL_HOSTS:
        said.append(f"{base_url} starts with http://, so your text and your key travel to {host_of(base_url)} unencrypted.")
    return said

def chosen(store: OpportunityStore) -> tuple[Provider, str, str] | None:
    provider = PROVIDERS.get(store.setting("llm.provider") or "")
    if provider is None:
        return None
    # Only the compatible provider has a base URL of the applicant's choosing.
    base_url = (store.setting("llm.base_url") if provider.name == "compatible" else None) or provider.base_url
    return provider, store.setting("llm.model") or provider.default_model, base_url

def connect(store: OpportunityStore) -> Model | None:
    picked = chosen(store)
    if picked is None:
        return None
    provider, name, base_url = picked
    key = keys.get(provider, store.db_path.parent)
    if (provider.needs_key and not key) or not name:
        return None
    return HttpModel(provider, name, base_url, key)

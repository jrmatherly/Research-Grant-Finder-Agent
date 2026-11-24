import pytest
from helpers import fixture, model, model_for
from nih_grant_matcher.llm import PROVIDERS, ModelError, connect, list_models
from nih_grant_matcher.store import OpportunityStore

@pytest.mark.parametrize("name, wire", [("claude", "anthropic"), ("openai", "openai"), ("gemini", "gemini"), ("compatible", "openai")])
def test_each_provider_returns_the_text_of_its_reply(name, wire, post) -> None:
    post.reply(fixture(f"{wire}-ok"))
    done = model(name).complete("system text", "user text")
    assert done.text == "Hello." and done.truncated is False and done.input_tokens > 0
    assert "temperature" not in post.body and "top_p" not in post.body

@pytest.mark.parametrize("wire", ["anthropic", "openai", "gemini"])
def test_a_reply_cut_at_the_token_limit_says_so(wire, post) -> None:
    post.reply(fixture(f"{wire}-truncated"))
    assert model_for(wire).complete("s", "u").truncated is True

# The vendor page names Authorization: Bearer for direct HTTP and calls x-api-key a legacy fallback.
def test_the_claude_request_has_its_headers_and_no_key_in_the_url(post) -> None:
    post.reply(fixture("anthropic-ok"))
    model("claude", key="sk-test-123").complete("s", "u")
    assert post.headers["Authorization"] == "Bearer sk-test-123" and post.headers["Anthropic-version"] == "2026-10-21"
    assert "sk-test-123" not in post.url and post.body["model"] == "claude-opus-5-5"
    assert post.body["fallbacks"] == "default" and post.headers["Anthropic-beta"] == "server-side-fallback-2026-07-01"

def test_gemini_asks_not_to_be_stored(post) -> None:
    post.reply(fixture("gemini-ok"))
    model("gemini", key="g-key-1").complete("s", "u", max_tokens=99)
    assert post.body["store"] is False and post.body["generation_config"] == {"max_output_tokens": 99}
    assert post.headers["X-goog-api-key"] == "g-key-1" and "g-key-1" not in post.url

# Ollama's page lists max_tokens and not max_completion_tokens, and its server ignores a field it does not know.
def test_a_local_server_needs_no_key(post) -> None:
    post.reply(fixture("openai-ok"))
    model("compatible", key=None, base_url="http://localhost:11434/v1").complete("s", "u")
    assert "Authorization" not in post.headers and post.url == "http://localhost:11434/v1/chat/completions"
    assert post.body["max_tokens"] == 16000 and "max_completion_tokens" not in post.body

@pytest.mark.parametrize("status, kind, sent", [(401, "auth", 1), (429, "rate", 2), (529, "overload", 2), (500, "overload", 1)])
def test_an_http_error_has_a_kind_and_only_an_unprocessed_request_is_sent_again(status, kind, sent, post) -> None:
    post.fail(status, fixture("anthropic-error"))
    post.fail(status, fixture("anthropic-error"))
    with pytest.raises(ModelError) as failed:
        model("claude").complete("s", "u")
    assert failed.value.kind == kind and post.calls == sent

def test_a_rate_limit_is_retried_once_after_the_wait_the_provider_names(post) -> None:
    post.fail(429, fixture("anthropic-error"), headers={"retry-after": "7"})
    post.reply(fixture("anthropic-ok"))
    assert model("claude").complete("s", "u").text == "Hello." and post.calls == 2 and post.slept == [7]

@pytest.mark.parametrize("error", [{"type": "insufficient_quota", "message": "You exceeded your current quota."}, {"type": "rate_limit_error", "code": "organization_usage_limit_exceeded", "message": "Usage limit."}, {"type": "rate_limit_error", "message": "Spend cap.", "details": {"error_code": "enforced_spend_limit_reached"}}])
def test_a_quota_error_is_not_retried(error, post) -> None:
    post.fail(429, {"error": error})
    with pytest.raises(ModelError) as failed:
        model("openai").complete("s", "u")
    assert failed.value.kind == "quota" and post.calls == 1

def test_an_http_error_never_contains_the_key(post) -> None:
    post.fail(401, {"error": {"message": "Incorrect API key provided: sk-test-123. Key ending ...-123 is not valid."}})
    with pytest.raises(ModelError) as failed:
        model("openai", key="sk-test-123").complete("s", "u")
    assert "sk-test-123" not in str(failed.value) and "-123" not in str(failed.value) and "Incorrect API key" in str(failed.value)

@pytest.mark.parametrize("name, wire", [("claude", "anthropic"), ("openai", "openai"), ("gemini", "gemini")])
def test_an_error_says_what_the_provider_said(name, wire, post) -> None:
    post.fail(400, fixture(f"{wire}-error"))
    with pytest.raises(ModelError) as failed:
        model(name, key="sk-error-test").complete("s", "u")
    assert fixture(f"{wire}-error")["error"]["message"] in str(failed.value) and "400" in str(failed.value) and post.calls == 1

def test_a_dropped_connection_says_a_charge_is_possible_and_is_not_retried(post) -> None:
    post.fail_with(TimeoutError("timed out"))
    with pytest.raises(ModelError, match="may have reached"):
        model("claude").complete("s", "u")
    assert post.calls == 1

# OpenAI rejects max_tokens on its reasoning models, and a server behind the compatible provider can be one of them.
@pytest.mark.parametrize("name, sent, then", [("openai", "max_completion_tokens", "max_tokens"), ("compatible", "max_tokens", "max_completion_tokens")])
def test_a_server_that_wants_the_other_token_limit_gets_it_on_the_second_request(name, sent, then, post) -> None:
    post.fail(400, {"error": {"message": f"Unsupported parameter: {sent}"}})
    post.reply(fixture("openai-ok"))
    assert model(name, key=None, base_url="http://localhost:11434/v1").complete("s", "u").text == "Hello."
    assert post.calls == 2 and then in post.body and sent not in post.body

def test_a_refusal_is_an_error_of_its_own_kind(post) -> None:
    post.reply({**fixture("anthropic-ok"), "stop_reason": "refusal", "content": [], "stop_details": {"type": "refusal", "category": "bio", "explanation": "Declined."}})
    with pytest.raises(ModelError) as failed:
        model("claude").complete("s", "u")
    assert failed.value.kind == "refused" and "Declined." in str(failed.value)

def test_an_openai_refusal_is_refused_too(post) -> None:
    ok = fixture("openai-ok")
    post.reply({**ok, "choices": [{**ok["choices"][0], "message": {"role": "assistant", "content": None, "refusal": "I can't help with that."}}]})
    with pytest.raises(ModelError) as failed:
        model("openai").complete("s", "u")
    assert failed.value.kind == "refused"

def test_a_failed_gemini_interaction_is_an_error(post) -> None:
    post.reply({**fixture("gemini-ok"), "status": "failed", "steps": []})
    with pytest.raises(ModelError, match="failed"):
        model("gemini").complete("s", "u")

@pytest.mark.parametrize("name, reply, names", [
    ("claude", {"data": [{"id": "claude-opus-5-5", "type": "model"}], "has_more": False}, ["claude-opus-5-5"]),
    ("openai", {"object": "list", "data": [{"id": "model-id-0", "object": "model"}]}, ["model-id-0"]),
    ("gemini", {"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/embedding-1", "supportedGenerationMethods": ["embedContent"]}]}, ["gemini-3.8-flash"])])
def test_each_provider_lists_its_models(name, reply, names, post) -> None:
    post.reply(reply)
    assert list_models(PROVIDERS[name], PROVIDERS[name].base_url, "sk-list-1") == names
    assert "sk-list-1" not in post.url and "sk-list-1" in " ".join(post.headers.values()) and post.body is None

def test_connect_needs_a_provider_and_its_key(tmp_path, monkeypatch) -> None:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    for provider in PROVIDERS.values():
        monkeypatch.delenv(provider.key_env, raising=False)
        monkeypatch.delenv(provider.key_env + "_FILE", raising=False)
    assert connect(store) is None
    store.set_setting("llm.provider", "claude")
    monkeypatch.setattr("nih_grant_matcher.keys.get", lambda provider, data_dir: None)
    assert connect(store) is None
    monkeypatch.setattr("nih_grant_matcher.keys.get", lambda provider, data_dir: "sk-1")
    assert (connect(store).name, connect(store).host) == ("claude-opus-5-5", "api.anthropic.com")
    store.set_setting("llm.provider", "compatible")
    store.set_setting("llm.base_url", "http://localhost:11434/v1")
    store.set_setting("llm.model", "llama9")
    monkeypatch.setattr("nih_grant_matcher.keys.get", lambda provider, data_dir: None)
    assert (connect(store).name, connect(store).host) == ("llama9", "localhost")
    store.close()

import http.server, io, threading, traceback, urllib.error
import pytest
from helpers import error_with_unreadable_body, fixture, model, model_for, strict_open
from nih_grant_matcher import llm
from nih_grant_matcher.llm import PROVIDERS, ModelError, cautions, connect, list_models, writes_text
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

# Anthropic's page: a key that is not scoped to one workspace must name one in anthropic-workspace-id on each request.
def test_a_claude_workspace_goes_on_the_request_and_the_model_list_and_only_when_set(post) -> None:
    post.reply(fixture("anthropic-ok"))
    model("claude", workspace="wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ").complete("s", "u")
    assert post.headers["Anthropic-workspace-id"] == "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ"
    post.reply({"data": [], "has_more": False})
    list_models(PROVIDERS["claude"], PROVIDERS["claude"].base_url, "k", "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ")
    assert post.headers["Anthropic-workspace-id"] == "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ"
    post.reply(fixture("anthropic-ok"))
    model("claude").complete("s", "u")
    assert "Anthropic-workspace-id" not in post.headers

@pytest.mark.parametrize("name, wire", [("openai", "openai"), ("gemini", "gemini"), ("compatible", "openai")])
def test_a_saved_workspace_reaches_no_other_provider(name, wire, tmp_path, monkeypatch, post) -> None:
    monkeypatch.setattr("nih_grant_matcher.keys.get", lambda provider, data_dir: "sk-1")
    store = OpportunityStore(tmp_path / "g.sqlite3")
    for setting, value in (("llm.provider", name), ("llm.model", "m1"), ("llm.workspace", "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ")):
        store.set_setting(setting, value)
    try:
        post.reply(fixture(f"{wire}-ok"))
        connect(store).complete("s", "u")
        post.reply({"data": [], "models": []})
        list_models(PROVIDERS[name], PROVIDERS[name].base_url, "sk-1", llm.workspace(store))
    finally:
        store.close()
    assert "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ" not in " ".join(post.headers.values()) + post.url

@pytest.mark.parametrize("value", ["wrkspc_01Jw\r\nX-Other: 1", "wrkspc_01Jw\xe9", "01JwQvzr7rXLA5AGx3HKfFUJ", "sk-ant-api03-secret"])
def test_a_workspace_that_is_not_an_id_is_refused_without_repeating_it(value) -> None:
    with pytest.raises(ValueError, match="starts with wrkspc_") as refused:
        llm.checked_workspace(value)
    assert value not in str(refused.value) and "secret" not in str(refused.value)

def test_a_workspace_is_trimmed_and_an_empty_one_clears_it() -> None:
    assert (llm.checked_workspace(" wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ\n"), llm.checked_workspace("  ")) == ("wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ", "")

# The page's three answers: no header for a key that needs one (400), an ID of the wrong form (400), and a workspace the key cannot use (404).
@pytest.mark.parametrize("status, message", [(400, "This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header with the ID of the workspace to use. Add the header, or use an API key that is scoped to a workspace."), (400, "anthropic-workspace-id header must be a valid workspace ID."), (404, "Workspace `wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ` not found.")])
def test_a_claude_workspace_error_says_where_to_set_the_workspace(status, message, post) -> None:
    post.fail(status, {"type": "error", "error": {"type": "invalid_request_error" if status == 400 else "not_found_error", "message": message}})
    with pytest.raises(ModelError) as failed:
        model("claude", key="sk-test-123").complete("s", "u")
    assert message in str(failed.value) and "platform.claude.com/settings/workspaces" in str(failed.value) and "models --workspace" in str(failed.value) and post.calls == 1

def test_a_404_that_names_no_workspace_gets_no_workspace_hint(post) -> None:
    post.fail(404, fixture("anthropic-error"))
    with pytest.raises(ModelError) as failed:
        model("claude").complete("s", "u")
    assert "settings/workspaces" not in str(failed.value)

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

@pytest.mark.parametrize("exc", [TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))])
def test_a_test_that_times_out_says_so_and_does_not_blame_the_key(exc, post) -> None:
    post.fail_with(exc)
    with pytest.raises(ModelError) as failed:
        model("gemini").complete("s", "u", probe=True)
    assert "No answer came within 60 seconds" in str(failed.value) and "says nothing about your key" in str(failed.value)

def test_a_refusal_when_no_key_was_sent_says_none_is_saved(post) -> None:
    post.fail(401, {"error": {"message": "Missing bearer authentication in header"}})
    with pytest.raises(ModelError) as failed:
        model("compatible", key=None, base_url="http://localhost:11434/v1").complete("s", "u", probe=True)
    assert "none is saved" in str(failed.value) and "mistyped" not in str(failed.value)

def test_a_probe_waits_a_minute_at_most_and_a_draft_ten(post, monkeypatch) -> None:
    waits = []
    monkeypatch.setattr(llm, "_open", lambda request, timeout=None: waits.append(timeout) or post(request))
    for probe in (True, False):
        post.reply(fixture("gemini-ok"))
        model("gemini").complete("s", "u", probe=probe)
    assert waits == [60, 600]

# OpenAI rejects max_tokens on its reasoning models, and a server behind the compatible provider can be one of them.
@pytest.mark.parametrize("name, sent, then", [("openai", "max_completion_tokens", "max_tokens"), ("compatible", "max_tokens", "max_completion_tokens")])
def test_a_server_that_wants_the_other_token_limit_gets_it_on_the_second_request(name, sent, then, post) -> None:
    post.fail(400, {"error": {"message": f"Unsupported parameter: {sent}"}})
    post.reply(fixture("openai-ok"))
    assert model(name, key=None, base_url="http://localhost:11434/v1").complete("s", "u").text == "Hello."
    assert post.calls == 2 and then in post.body and sent not in post.body

# OpenAI's page: from o1 on, developer messages replace system messages. Ollama's page lists system and no developer role.
@pytest.mark.parametrize("name, role", [("openai", "developer"), ("compatible", "system")])
def test_the_instructions_go_in_the_role_each_provider_documents(name, role, post) -> None:
    post.reply(fixture("openai-ok"))
    model(name, base_url="http://localhost:11434/v1" if name == "compatible" else "").complete("the instructions", "u")
    assert post.body["messages"] == [{"role": role, "content": "the instructions"}, {"role": "user", "content": "u"}]

@pytest.mark.parametrize("name, sent, then", [("openai", "developer", "system"), ("compatible", "system", "developer")])
def test_a_server_that_refuses_the_role_gets_the_other_one_on_the_second_request(name, sent, then, post) -> None:
    post.fail(400, {"error": {"message": f"Unsupported value: 'messages[0].role' does not support '{sent}' with this model.", "type": "invalid_request_error", "param": "messages[0].role", "code": "unsupported_value"}})
    post.reply(fixture("openai-ok"))
    assert model(name, base_url="http://localhost:11434/v1" if name == "compatible" else "").complete("s", "u").text == "Hello."
    assert post.calls == 2 and post.body["messages"][0] == {"role": then, "content": "s"} and post.body["messages"][1]["role"] == "user"

def test_when_the_other_role_is_refused_too_the_first_error_is_shown_and_nothing_more_is_sent(post) -> None:
    post.fail(400, {"error": {"message": "Unsupported value: 'messages[0].role' does not support 'developer' with this model."}})
    post.fail(400, {"error": {"message": "Unsupported value: 'messages[0].role' does not support 'system' with this model."}})
    with pytest.raises(ModelError, match="'developer'"):
        model("openai").complete("s", "u")
    assert post.calls == 2

def test_a_400_that_names_neither_the_role_nor_the_limit_is_not_sent_again(post) -> None:
    post.fail(400, {"error": {"message": "The developer of this model has not enabled it for your project."}})
    with pytest.raises(ModelError):
        model("openai").complete("s", "u")
    assert post.calls == 1

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

@pytest.mark.parametrize("name, reply, names", [
    ("claude", {"data": [{"id": "claude-opus-5-5", "type": "model", "lifecycle": "active"}, {"id": "claude-opus-4-5", "type": "model", "lifecycle": "deprecated"}], "has_more": False}, ["claude-opus-5-5"]),
    ("openai", {"object": "list", "data": [{"id": "model-id-0", "object": "model", "created": 1686935002}, {"id": "gpt-6.2-astra", "object": "model", "created": 1790000000}]}, ["gpt-6.2-astra", "model-id-0"])])
def test_a_list_leaves_out_a_deprecated_model_and_puts_the_newest_first(name, reply, names, post) -> None:
    post.reply(reply)
    assert list_models(PROVIDERS[name], PROVIDERS[name].base_url, "k") == names

@pytest.mark.parametrize("name, listed, kept", [
    ("openai", ["text-embedding-3-small", "gpt-5.5-pro", "gpt-6.2-astra", "whisper-1"], ["gpt-6.2-astra"]),
    ("gemini", ["gemini-4-hydrogen", "gemini-2.5-flash-preview-tts", "gemma-4-31b-it"], ["gemini-4-hydrogen", "gemma-4-31b-it"]),
    ("claude", ["claude-opus-5-5"], ["claude-opus-5-5"]),
    ("compatible", ["nomic-embed-text", "llama9"], ["nomic-embed-text", "llama9"])])
def test_only_models_that_write_text_are_offered(name, listed, kept) -> None:
    assert writes_text(PROVIDERS[name], listed) == kept

def test_a_key_with_a_line_break_stays_out_of_the_error(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_open", strict_open)
    with pytest.raises(ModelError) as failed:
        model("claude", key="sk-leak\r9z8y").complete("s", "u")
    shown = "".join(traceback.format_exception_only(failed.value))
    assert "sk-leak" not in shown and "9z8y" not in shown and "not printable ASCII" in shown and failed.value.__context__ is None and failed.value.__cause__ is None

def _serve(answer) -> http.server.HTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.server.seen.append(self.headers.get("Authorization"))
            answer(self)
        def log_message(self, *args) -> None: pass
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    httpd.seen = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

def _redirect_to(port: int):
    def answer(handler) -> None:
        handler.send_response(302)
        handler.send_header("Location", f"http://127.0.0.1:{port}/elsewhere/v1/models")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
    return answer

def _models_reply(handler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(b'{"data": []}')

def test_a_redirect_is_not_followed_so_the_key_reaches_no_other_server(monkeypatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    other = _serve(_models_reply)
    first = _serve(_redirect_to(other.server_port))
    try:
        list_models(PROVIDERS["openai"], f"http://127.0.0.1:{first.server_port}/v1", "sk-redirect-1")
        failed = None
    except ModelError as exc:
        failed = exc
    finally:
        for httpd in (first, other):
            httpd.shutdown()
            httpd.server_close()
    assert other.seen == [] and first.seen == ["Bearer sk-redirect-1"]
    assert failed.kind == "other" and "redirect" in str(failed) and "127.0.0.1" in str(failed) and "/elsewhere" not in str(failed)

def test_an_openai_reply_whose_text_is_not_a_string_has_no_text(post) -> None:
    ok = fixture("openai-ok")
    post.reply({**ok, "choices": [{**ok["choices"][0], "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello."}]}}]})
    with pytest.raises(ModelError, match="no text") as failed:
        model("openai").complete("s", "u")
    assert "choices, created, id, model, object, service_tier, usage" in str(failed.value)

def test_a_reply_in_another_shape_names_its_top_level_fields_and_no_values(post) -> None:
    post.reply({"type": "message", "id": "msg-1", "result": "sk-test-123 said hello"})
    with pytest.raises(ModelError, match="not in the form") as failed:
        model("claude", key="sk-test-123").complete("s", "u")
    assert "id, result, type" in str(failed.value) and "msg-1" not in str(failed.value) and "hello" not in str(failed.value)

@pytest.mark.parametrize("status, shown", [(400, "max_completion_tokens is too large"), (500, "overloaded")])
def test_when_the_other_token_limit_fails_too_the_error_that_named_the_fault_is_shown(status, shown, post) -> None:
    post.fail(400, {"error": {"message": "max_completion_tokens is too large: 16000. This model supports at most 8192 completion tokens."}})
    post.fail(status, {"error": {"message": "Unrecognized request argument supplied: max_tokens" if status == 400 else "overloaded"}})
    with pytest.raises(ModelError, match=shown):
        model("openai", key="sk-test-123").complete("s", "u")
    assert post.calls == 2

@pytest.mark.parametrize("name, wire, usage", [("claude", "anthropic", {"input_tokens": None, "output_tokens": None}), ("openai", "openai", {"prompt_tokens": None, "completion_tokens": None}), ("gemini", "gemini", {"total_input_tokens": None})])
def test_a_missing_or_null_token_count_is_zero(name, wire, usage, post) -> None:
    post.reply({**fixture(f"{wire}-ok"), "usage": usage})
    done = model(name).complete("s", "u")
    assert (done.input_tokens, done.output_tokens) == (0, 0)

def test_a_model_list_of_the_wrong_shape_is_a_model_error(post) -> None:
    post.reply({"models": ["gemini-3.8-flash"]})
    with pytest.raises(ModelError, match="not in the form"):
        list_models(PROVIDERS["gemini"], PROVIDERS["gemini"].base_url, "g-key-1")

def test_a_retry_after_over_30_seconds_waits_30(post) -> None:
    post.fail(429, fixture("anthropic-error"), headers={"retry-after": "3600"})
    post.reply(fixture("anthropic-ok"))
    model("claude").complete("s", "u")
    assert post.slept == [30.0]

def test_an_openai_reply_cut_by_the_content_filter_is_refused_and_not_returned(post) -> None:
    ok = fixture("openai-ok")
    post.reply({**ok, "choices": [{**ok["choices"][0], "message": {"role": "assistant", "content": "We study"}, "finish_reason": "content_filter"}]})
    with pytest.raises(ModelError, match="content filter") as failed:
        model("openai").complete("s", "u")
    assert failed.value.kind == "refused"

def test_a_claude_reply_that_filled_the_context_window_is_cut_off(post) -> None:
    post.reply({**fixture("anthropic-ok"), "stop_reason": "model_context_window_exceeded"})
    assert model("claude").complete("s", "u").truncated is True

@pytest.mark.parametrize("name", ["claude", "openai", "gemini"])
def test_a_base_url_saved_for_a_compatible_server_is_not_used_for_another_provider(name, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nih_grant_matcher.keys.get", lambda provider, data_dir: "sk-1")
    store = OpportunityStore(tmp_path / "g.sqlite3")
    for setting, value in (("llm.provider", "compatible"), ("llm.base_url", "http://gpu.example:8000/v1"), ("llm.provider", name), ("llm.model", "m1")):
        store.set_setting(setting, value)
    try:
        assert (connect(store).base_url, connect(store).host) == (PROVIDERS[name].base_url, llm.host_of(PROVIDERS[name].base_url))
    finally:
        store.close()

@pytest.mark.parametrize("header", ["-5", "nan", "soon"])
def test_a_retry_after_that_is_not_a_wait_means_two_seconds(header, post) -> None:
    post.fail(429, fixture("anthropic-error"), headers={"retry-after": header})
    post.reply(fixture("anthropic-ok"))
    model("claude").complete("s", "u")
    assert post.slept == [2.0]

def test_a_reply_that_is_not_json_is_shown_without_the_key(post) -> None:
    post.queue.append(lambda url: io.BytesIO(b"<html>Bad key sk-test-123</html>"))
    with pytest.raises(ModelError, match="did not return JSON") as failed:
        model("openai", key="sk-test-123").complete("s", "u")
    assert "sk-test" not in str(failed.value) and "reached api.openai.com, so it may be charged. It was not sent again." in str(failed.value)

def test_an_error_body_cut_short_does_not_keep_part_of_the_key(post) -> None:
    def failed_with_html(url: str):
        raise urllib.error.HTTPError(url, 502, "", {}, io.BytesIO(("x" * 292 + " sk-test-123").encode()))
    post.queue.append(failed_with_html)
    with pytest.raises(ModelError) as failed:
        model("openai", key="sk-test-123").complete("s", "u")
    assert "sk-test" not in str(failed.value)

def test_an_address_in_capitals_still_gets_the_unencrypted_warning() -> None:
    assert any("unencrypted" in said for said in cautions(PROVIDERS["compatible"], "HTTP://gpu.example:8000/v1"))

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

@pytest.mark.parametrize("call", [lambda key: model("claude", key=key).complete("s", "u"), lambda key: list_models(PROVIDERS["openai"], PROVIDERS["openai"].base_url, key)])
def test_a_key_with_a_latin_1_character_and_a_line_break_is_refused_before_a_request(call, monkeypatch) -> None:
    monkeypatch.setattr(llm, "_open", strict_open)
    with pytest.raises(ModelError) as failed:
        call("sk-leak\xe9\r9z8y")
    shown = "".join(traceback.format_exception_only(failed.value))
    assert "sk-leak" not in shown and "9z8y" not in shown and "not printable ASCII" in shown

def test_an_openai_reply_with_no_text_at_the_token_limit_is_cut_off(post) -> None:
    ok = fixture("openai-ok")
    post.reply({**ok, "choices": [{**ok["choices"][0], "message": {"role": "assistant", "content": None}, "finish_reason": "length"}]})
    done = model("openai").complete("s", "u")
    assert (done.text, done.truncated) == ("", True)

class _ReplyThatBreaks(io.BytesIO):
    def read(self, *args):
        raise ValueError("the reply could not be read")

def test_a_failure_while_the_reply_is_read_says_the_request_may_have_reached_the_provider(post) -> None:
    post.queue.append(lambda url: _ReplyThatBreaks())
    with pytest.raises(ModelError, match="may have reached api.openai.com") as failed:
        model("openai").complete("s", "u")
    assert post.calls == 1 and "the reply could not be read" in str(failed.value)

@pytest.mark.parametrize("broken", [TimeoutError("timed out"), ConnectionResetError(54, "Connection reset by peer"), http.client.IncompleteRead(b"{", 120), OSError("reset after sk-test-123")])
def test_an_error_whose_body_cannot_be_read_is_a_model_error_without_the_key(broken, post) -> None:
    post.queue.append(error_with_unreadable_body(broken))
    with pytest.raises(ModelError, match="may have reached api.openai.com") as failed:
        model("openai", key="sk-test-123").complete("s", "u")
    assert "502" in str(failed.value) and "not sent again" in str(failed.value) and "sk-test" not in str(failed.value) and post.calls == 1

def test_a_redirect_to_an_address_that_does_not_parse_is_a_model_error(post) -> None:
    def redirected(url: str):
        raise urllib.error.HTTPError(url, 302, "Found", {"location": "http://[::1/v1"}, io.BytesIO(b""))
    post.queue.append(redirected)
    with pytest.raises(ModelError, match="302") as failed:
        model("openai").complete("s", "u")
    assert "api.openai.com" in str(failed.value) and post.calls == 1

def test_a_failure_before_the_request_leaves_does_not_say_it_may_have_reached_the_provider(post) -> None:
    post.fail_with(ValueError("Invalid header value"))
    with pytest.raises(ModelError) as failed:
        model("openai").complete("s", "u")
    assert "may have reached" not in str(failed.value) and "Invalid header value" in str(failed.value)

@pytest.mark.parametrize("status, error, says", [
    (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, "refused this request"),
    (429, {"error": {"code": "quota_exceeded", "message": "You have exceeded your daily quota."}}, "quota, credit or spending limit"),
    (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, model: gemini-4-argon"}}, "quota, credit or spending limit"),
    (503, {"error": {"code": "service_unavailable", "message": "gemini-4-hydrogen is currently experiencing high demand."}}, "says nothing about your key"),
    (502, {"error": {"code": 502, "status": "UNAVAILABLE", "message": "Bad gateway."}}, "says nothing about your key"),
    (504, {"error": {"code": 504, "status": "DEADLINE_EXCEEDED", "message": "Deadline expired before operation could complete."}}, "says nothing about your key"),
    (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0."}}, "quota, credit or spending limit"),
    (404, {"error": {"code": "model_not_found", "message": "The specified model was not found."}}, "did not find this model")])
def test_a_failed_test_says_what_it_means_for_the_key(status, error, says, post) -> None:
    post.fail(status, error)
    post.fail(status, error)
    with pytest.raises(ModelError) as failed:
        model("gemini", key="sk-test-123").complete("s", "u", probe=True)
    assert error["error"]["message"] in str(failed.value) and says in str(failed.value) and post.calls == 1 and post.slept == []

def test_a_429_with_a_limit_above_zero_is_still_a_rate_limit(post) -> None:
    post.fail(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: requests per minute, limit: 15"}})
    post.reply(fixture("gemini-ok"))
    assert model("gemini").complete("s", "u").text == "Hello." and post.calls == 2

def test_a_429_with_a_fractional_limit_is_a_rate_limit_not_a_quota_of_zero(post) -> None:
    post.fail(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Rate exceeded, limit: 0.5 per second"}})
    with pytest.raises(ModelError) as failed:
        model("gemini").complete("s", "u", probe=True)
    assert failed.value.kind == "rate"

def test_a_draft_does_not_wait_and_retry_a_quota_of_zero(post) -> None:
    post.fail(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, model: gemini-4-argon"}})
    with pytest.raises(ModelError) as failed:
        model("gemini").complete("s", "u")
    assert (failed.value.kind, post.calls, post.slept) == ("quota", 1, [])

def test_a_model_list_that_fails_is_not_told_to_list_the_models(post) -> None:
    post.fail(404, {"error": {"message": "Not Found"}})
    with pytest.raises(ModelError) as failed:
        list_models(PROVIDERS["compatible"], "http://localhost:11434", None)
    assert "did not find this model" not in str(failed.value)

def test_a_404_that_is_not_an_api_error_is_not_blamed_on_the_model(post) -> None:
    # A wrong Base URL path answers 404 with a plain page, and the model's name is not the cause.
    post.fail_with(urllib.error.HTTPError("http://localhost:11434/chat/completions", 404, "", {}, io.BytesIO(b"404 page not found")))
    with pytest.raises(ModelError) as failed:
        model("compatible").complete("s", "u")
    assert "404 page not found" in str(failed.value) and "did not find this model" not in str(failed.value)

import json, stat
import pytest
from helpers import FakeSecurity
from nih_grant_matcher import keys
from nih_grant_matcher.llm import PROVIDERS
from nih_grant_matcher.store import OpportunityStore

@pytest.fixture(autouse=True)
def no_keys_in_the_environment(monkeypatch) -> None:
    # A developer's own key would otherwise decide these tests.
    for provider in PROVIDERS.values():
        monkeypatch.delenv(provider.key_env, raising=False)
        monkeypatch.delenv(provider.key_env + "_FILE", raising=False)
    keys.forget()

@pytest.fixture
def linux(monkeypatch) -> None:
    monkeypatch.setattr(keys, "PLATFORM", "linux")

@pytest.fixture
def mac(monkeypatch) -> FakeSecurity:
    fake = FakeSecurity()
    monkeypatch.setattr(keys, "PLATFORM", "darwin")
    monkeypatch.setattr(keys, "_run", fake)
    return fake

def test_the_environment_wins_then_the_secret_file_then_the_store(tmp_path, monkeypatch, linux) -> None:
    keys.save(PROVIDERS["claude"], "from-store", tmp_path)
    assert keys.get(PROVIDERS["claude"], tmp_path) == "from-store"
    secret = tmp_path / "secret"
    secret.write_text("from-secret-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(secret))
    assert keys.get(PROVIDERS["claude"], tmp_path) == "from-secret-file"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert keys.get(PROVIDERS["claude"], tmp_path) == "from-env"

def test_on_a_mac_the_key_goes_to_the_keychain_on_standard_input(tmp_path, mac) -> None:
    where = keys.save(PROVIDERS["claude"], "sk-test-123", tmp_path)
    assert "Keychain" in where and list(tmp_path.iterdir()) == []
    assert mac.items == {("Grant Matcher", "claude"): "sk-test-123"}
    assert mac.argv[-1] == ["/usr/bin/security", "-i"] and "sk-test-123".encode().hex() in mac.stdin[-1]
    assert not any("sk-test-123" in part or "sk-test-123".encode().hex() in part for call in mac.argv for part in call)
    assert keys.get(PROVIDERS["claude"], tmp_path) == "sk-test-123"

def test_the_keychain_is_read_once_per_process(tmp_path, mac) -> None:
    keys.save(PROVIDERS["claude"], "sk-test-123", tmp_path)
    before = len(mac.argv)
    assert [keys.get(PROVIDERS["claude"], tmp_path) for _ in range(5)] == ["sk-test-123"] * 5
    assert len(mac.argv) - before <= 1
    keys.delete(PROVIDERS["claude"], tmp_path)
    assert keys.get(PROVIDERS["claude"], tmp_path) is None and mac.items == {}

def test_a_key_that_is_not_printable_ascii_is_refused(tmp_path, mac) -> None:
    for bad in ("kéy", "two\nlines", ""):
        with pytest.raises(ValueError):
            keys.save(PROVIDERS["openai"], bad, tmp_path)
    assert mac.items == {} and mac.argv == []

def test_a_key_with_quotes_and_spaces_round_trips(tmp_path, mac) -> None:
    keys.save(PROVIDERS["compatible"], 'a "quoted" key with spaces', tmp_path)
    keys.forget()
    assert keys.get(PROVIDERS["compatible"], tmp_path) == 'a "quoted" key with spaces'

@pytest.mark.parametrize("code, words", [(36, "locked"), (51, "declined"), (128, "cancelled")])
def test_a_keychain_that_cannot_answer_is_an_error_and_not_a_missing_key(tmp_path, mac, code, words) -> None:
    mac.exit_with = code
    with pytest.raises(keys.KeychainError, match=words):
        keys.get(PROVIDERS["claude"], tmp_path)

def test_off_a_mac_the_key_file_is_mode_0600(tmp_path, linux) -> None:
    where = keys.save(PROVIDERS["openai"], "sk-1", tmp_path)
    path = tmp_path / "llm-keys.json"
    assert str(path) in where and stat.S_IMODE(path.stat().st_mode) == 0o600
    keys.delete(PROVIDERS["openai"], tmp_path)
    assert keys.get(PROVIDERS["openai"], tmp_path) is None

def test_saving_a_second_key_keeps_the_first_and_fixes_a_loose_mode(tmp_path, linux) -> None:
    keys.save(PROVIDERS["openai"], "sk-1", tmp_path)
    path = tmp_path / "llm-keys.json"
    path.chmod(0o644)
    keys.save(PROVIDERS["claude"], "sk-2", tmp_path)
    assert (keys.get(PROVIDERS["openai"], tmp_path), keys.get(PROVIDERS["claude"], tmp_path)) == ("sk-1", "sk-2")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and [p.name for p in tmp_path.iterdir()] == ["llm-keys.json"]

@pytest.mark.parametrize("source", ["variable", "file", "store"])
def test_a_key_with_a_line_break_inside_is_refused_without_quoting_it(source, tmp_path, monkeypatch, linux) -> None:
    bad, secret, stored = "sk-leak\r9z8y\n", tmp_path / "secret", tmp_path / "llm-keys.json"
    if source == "variable":
        monkeypatch.setenv("OPENAI_API_KEY", bad)
    elif source == "file":
        secret.write_text(bad, encoding="utf-8")
        monkeypatch.setenv("OPENAI_API_KEY_FILE", str(secret))
    else:
        stored.write_text(json.dumps({"openai": bad}), encoding="utf-8")
    with pytest.raises(keys.UnreadableKey) as failed:
        keys.get(PROVIDERS["openai"], tmp_path)
    names = {"variable": "OPENAI_API_KEY", "file": str(secret), "store": str(stored)}[source]
    assert names in str(failed.value) and "sk-leak" not in str(failed.value) and "9z8y" not in str(failed.value)

def test_a_key_is_stripped_from_every_source(tmp_path, monkeypatch, linux) -> None:
    (tmp_path / "llm-keys.json").write_text(json.dumps({"openai": " sk-1\r\n"}), encoding="utf-8")
    assert keys.get(PROVIDERS["openai"], tmp_path) == "sk-1"
    monkeypatch.setenv("OPENAI_API_KEY", " sk-2\n")
    assert keys.get(PROVIDERS["openai"], tmp_path) == "sk-2"

@pytest.mark.parametrize("text", ["{not json", "[]", '{"openai": 7}'])
def test_a_key_file_that_cannot_be_read_names_itself_and_is_not_replaced(text, tmp_path, linux) -> None:
    path = tmp_path / "llm-keys.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(keys.UnreadableKey, match="cannot be read") as failed:
        keys.get(PROVIDERS["openai"], tmp_path)
    assert str(path) in str(failed.value)
    with pytest.raises(keys.UnreadableKey, match="cannot be read"):
        keys.save(PROVIDERS["claude"], "sk-2", tmp_path)
    assert path.read_text(encoding="utf-8") == text

def test_a_keychain_error_is_kept_until_a_key_is_saved(tmp_path, mac) -> None:
    mac.exit_with = 51
    for _ in range(3):
        with pytest.raises(keys.KeychainError, match="declined"):
            keys.get(PROVIDERS["claude"], tmp_path)
    assert len(mac.argv) == 1
    mac.exit_with = None
    keys.save(PROVIDERS["claude"], "sk-new-1", tmp_path)
    assert keys.get(PROVIDERS["claude"], tmp_path) == "sk-new-1"

def test_a_failed_keychain_write_raises_and_saves_nothing(tmp_path, mac) -> None:
    mac.exit_with = 36
    with pytest.raises(keys.KeychainError, match="locked"):
        keys.save(PROVIDERS["claude"], "sk-new-1", tmp_path)
    mac.exit_with = None
    assert keys.get(PROVIDERS["claude"], tmp_path) is None

def test_no_key_reaches_the_database(tmp_path, linux) -> None:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    keys.save(PROVIDERS["claude"], "sk-secret-9", tmp_path)
    store.set_setting("llm.provider", "claude")
    store.close()
    assert b"sk-secret-9" not in (tmp_path / "g.sqlite3").read_bytes()

@pytest.mark.parametrize("text", ["", " \n"])
def test_a_key_file_variable_that_names_an_empty_file_is_an_error_and_not_a_missing_key(text, tmp_path, monkeypatch, linux) -> None:
    keys.save(PROVIDERS["claude"], "sk-saved-1", tmp_path)
    empty = tmp_path / "secret"
    empty.write_text(text, encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(empty))
    with pytest.raises(keys.UnreadableKey, match="empty") as failed:
        keys.get(PROVIDERS["claude"], tmp_path)
    assert "ANTHROPIC_API_KEY_FILE" in str(failed.value) and str(empty) in str(failed.value)

def test_a_key_file_variable_that_names_no_file_names_the_variable_and_the_path(tmp_path, monkeypatch, linux) -> None:
    missing = tmp_path / "no-such-key"
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(missing))
    with pytest.raises(keys.UnreadableKey) as failed:
        keys.get(PROVIDERS["openai"], tmp_path)
    assert "OPENAI_API_KEY_FILE" in str(failed.value) and str(missing) in str(failed.value)

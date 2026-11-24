import stat
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

def test_no_key_reaches_the_database(tmp_path, linux) -> None:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    keys.save(PROVIDERS["claude"], "sk-secret-9", tmp_path)
    store.set_setting("llm.provider", "claude")
    store.close()
    assert b"sk-secret-9" not in (tmp_path / "g.sqlite3").read_bytes()

from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .llm import Provider

PLATFORM = sys.platform
SERVICE = "Grant Matcher"
SECURITY = "/usr/bin/security"
_run = subprocess.run
# Streamlit runs the page again on every click, and a burst of security processes has crashed securityd.
_cache: dict[tuple[str, str], str | None] = {}
KEYCHAIN_ERRORS = {36: "The login keychain is locked. Unlock it and try again.", 51: "The Keychain prompt was declined, so Grant Matcher cannot read the key.", 128: "The Keychain prompt was cancelled, so Grant Matcher cannot read the key."}

class KeychainError(RuntimeError):
    pass

def get(provider: Provider, data_dir: Path) -> str | None:
    if value := os.environ.get(provider.key_env):
        return value
    if path := os.environ.get(provider.key_env + "_FILE"):
        return Path(path).read_text(encoding="utf-8").strip()
    slot = _slot(provider, data_dir)
    if slot not in _cache:
        _cache[slot] = _keychain_read(provider.name) if PLATFORM == "darwin" else _load(_file(data_dir)).get(provider.name)
    return _cache[slot]

def where(provider: Provider, data_dir: Path) -> str:
    if os.environ.get(provider.key_env):
        return f"Read from {provider.key_env}"
    if os.environ.get(provider.key_env + "_FILE"):
        return f"Read from the file that {provider.key_env}_FILE names"
    return f"Saved in {_store(data_dir)}"

def save(provider: Provider, key: str, data_dir: Path) -> str:
    # security prints a value with a byte outside printable ASCII as hex, which a key of hex digits could not be told from.
    if not key or not all(" " <= c <= "~" for c in key):
        raise ValueError("An API key is one line of printable ASCII characters. Copy it again from the provider's page.")
    if PLATFORM == "darwin":
        line = f'add-generic-password -U -a "{provider.name}" -s "{SERVICE}" -X {key.encode().hex()}\n'
        # security -i keeps at most 4,019 bytes of a line and corrupts the rest.
        if len(line) > 4000:
            raise ValueError("This key is too long for the Keychain.")
        _check(_run([SECURITY, "-i"], input=line, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode)
    else:
        path = _file(data_dir)
        _write(path, {**_load(path), provider.name: key})
    _cache[_slot(provider, data_dir)] = key
    return _store(data_dir)

def delete(provider: Provider, data_dir: Path) -> None:
    if PLATFORM == "darwin":
        code = _run([SECURITY, "delete-generic-password", "-a", provider.name, "-s", SERVICE], capture_output=True, text=True).returncode
        if code != 44:
            _check(code)
    else:
        path = _file(data_dir)
        saved = _load(path)
        if saved.pop(provider.name, None) is not None:
            _write(path, saved)
    _cache[_slot(provider, data_dir)] = None

def forget() -> None:
    _cache.clear()

def _slot(provider: Provider, data_dir: Path) -> tuple[str, str]:
    # Resolved, because a relative folder names another place after a change of directory.
    return provider.name, str(Path(data_dir).resolve())

def _store(data_dir: Path) -> str:
    return "the macOS Keychain" if PLATFORM == "darwin" else str(_file(data_dir))

def _check(code: int) -> None:
    # A locked keychain must not read as no key, or the dashboard would ask for a key the applicant already saved.
    if code:
        raise KeychainError(KEYCHAIN_ERRORS.get(code, f"{SECURITY} failed with exit code {code}."))

def _keychain_read(name: str) -> str | None:
    done = _run([SECURITY, "find-generic-password", "-a", name, "-s", SERVICE, "-w"], capture_output=True, text=True)
    if done.returncode == 44:
        return None
    _check(done.returncode)
    return done.stdout.rstrip("\n")

def _file(data_dir: Path) -> Path:
    return Path(data_dir) / "llm-keys.json"

def _load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

def _write(path: Path, saved: dict[str, str]) -> None:
    # A new file made 0600 and moved into place: a crash leaves the old file whole, and a loosened mode is reset.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".new")
    temp.unlink(missing_ok=True)
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as out:
        json.dump(saved, out)
    os.replace(temp, path)

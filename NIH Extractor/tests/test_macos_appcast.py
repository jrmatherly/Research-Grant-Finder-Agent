import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "macos" / "make-appcast.sh"
SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"


def _run(tmp_path, env=None, dmg_exists=True, notes: str = "- A fix."):
    signer = tmp_path / "sign_update"
    # Prints a fixed signature, and succeeds on --verify.
    signer.write_text('#!/bin/bash\ncat > /dev/null\nfor a in "$@"; do [ "$a" = --verify ] && exit 0; done\necho "c2lnbmF0dXJl"\n')
    signer.chmod(0o755)
    dmg = tmp_path / "Grant-Matcher-1.2.3-arm64.dmg"
    if dmg_exists:
        dmg.write_bytes(b"x" * 1234)
    (tmp_path / "notes.md").write_text(notes)
    full = {**os.environ, "SPARKLE_ED_KEY": "c2VlZA==", "SIGN_UPDATE": str(signer), "RELEASE_NOTES": str(tmp_path / "notes.md"), **(env or {})}
    return subprocess.run(["/bin/bash", str(SCRIPT), str(dmg), "1.2.3"], capture_output=True, text=True, env=full)


def test_appcast_describes_the_release_asset(tmp_path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    item = ET.fromstring(result.stdout).find("channel/item")
    enclosure = item.find("enclosure")
    assert item.findtext(f"{SPARKLE}version") == "1.2.3" and item.findtext(f"{SPARKLE}shortVersionString") == "1.2.3"
    assert item.findtext(f"{SPARKLE}minimumSystemVersion") == "14.0.0" and item.findtext(f"{SPARKLE}hardwareRequirements") == "arm64"
    assert enclosure.get("url") == "https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/download/v1.2.3/Grant-Matcher-1.2.3-arm64.dmg"
    assert enclosure.get("length") == "1234" and enclosure.get(f"{SPARKLE}edSignature") == "c2lnbmF0dXJl"


def test_appcast_links_the_release_notes(tmp_path) -> None:
    item = ET.fromstring(_run(tmp_path).stdout).find("channel/item")
    assert "https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/tag/v1.2.3" in item.findtext("description")


def test_appcast_carries_the_release_notes_exactly(tmp_path) -> None:
    # "]]>" would end the CDATA section, and the rest must reach Sparkle as written.
    notes = "## Fixes\n\n- a & b < c ]]> d <b>x</b> $HOME `id`"
    description = ET.fromstring(_run(tmp_path, notes=notes).stdout).find("channel/item/description")
    assert description.text.startswith(notes + "\n\n") and description.get(f"{SPARKLE}format") == "markdown"


def test_no_appcast_without_release_notes(tmp_path) -> None:
    result = _run(tmp_path, notes="")
    assert result.returncode != 0 and result.stdout == "" and "notes.md" in result.stderr


def test_download_base_can_be_replaced(tmp_path) -> None:
    result = _run(tmp_path, env={"APPCAST_DOWNLOAD_BASE": "http://127.0.0.1:8811"})
    assert ET.fromstring(result.stdout).find("channel/item/enclosure").get("url") == "http://127.0.0.1:8811/Grant-Matcher-1.2.3-arm64.dmg"


def test_no_appcast_without_the_key(tmp_path) -> None:
    result = _run(tmp_path, env={"SPARKLE_ED_KEY": ""})
    assert result.returncode != 0 and result.stdout == "" and "SPARKLE_ED_KEY" in result.stderr


def test_no_appcast_for_a_missing_disk_image(tmp_path) -> None:
    result = _run(tmp_path, dmg_exists=False)
    assert result.returncode != 0 and result.stdout == "" and "Grant-Matcher-1.2.3-arm64.dmg" in result.stderr


def test_seed_reaches_the_signer_on_stdin_only(tmp_path) -> None:
    seen = tmp_path / "seen"
    signer = tmp_path / "recording_signer"
    signer.write_text(f'#!/bin/bash\necho "stdin=$(cat) args=$*" >> "{seen}"\nfor a in "$@"; do [ "$a" = --verify ] && exit 0; done\necho "c2lnbmF0dXJl"\n')
    signer.chmod(0o755)
    assert _run(tmp_path, env={"SIGN_UPDATE": str(signer)}).returncode == 0
    sign, verify = seen.read_text().splitlines()
    dmg = str(tmp_path / "Grant-Matcher-1.2.3-arm64.dmg")
    assert sign.startswith("stdin=c2VlZA== args=") and verify.startswith("stdin=c2VlZA== args=")
    assert "c2VlZA==" not in sign.split("args=")[1] and "c2VlZA==" not in verify.split("args=")[1]
    assert sign.endswith(dmg) and verify.endswith(f"{dmg} c2lnbmF0dXJl")


def test_the_version_in_pyproject_has_release_notes() -> None:
    import tomllib
    version = tomllib.loads((SCRIPT.parent.parent / "pyproject.toml").read_text())["project"]["version"]
    assert (SCRIPT.parent / "release-notes" / f"{version}.md").read_text().strip()

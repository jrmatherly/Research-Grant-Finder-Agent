# In-App Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An installed Grant Matcher finds a new release, shows the user what is new, installs it, and relaunches, so that nobody returns to the releases page after the first install.

**Architecture:** The app embeds Sparkle 2, the updater that `claude-multipass` already uses. The launcher loads `Sparkle.framework` through pyobjc, which the app already ships, and adds one menu item. The build copies a pinned Sparkle into the bundle after PyInstaller and signs it inside out. The release workflow signs the disk image with an EdDSA key, writes an `appcast.xml` feed, and attaches it to the release. The app reads the feed from the newest release.

**Tech Stack:** Python 3.13, PyInstaller 6.22, pywebview 6.2 on pyobjc 13, Sparkle 2.10.1, bash 3.2, GitHub Actions, pytest, uv.

**Spec:** Appendix A of this file. It holds the research findings, the spike that proved the design on 2026-11-23, and the owner's decisions. No separate spec exists.

## Owner decisions

The plan uses these defaults. Change one here before execution starts, and the tasks that name it follow.

| Decision | Default in this plan | The alternative |
| --- | --- | --- |
| Update key | A key of its own, in the Keychain account `net.matherly.grant-matcher` | Reuse the `claude-multipass` key. Sparkle's `generate_keys` help says one key serves every app. A shared key means one leak affects both apps. |
| Feed location | A release asset, read from `releases/latest/download/appcast.xml` | A file in a second repository, as `claude-multipass` does. That gives a manual gate before users see a release, and it needs one more step per release. |
| Automatic checks | `SUEnableAutomaticChecks` is `true`. The app checks once a day and asks nothing first. The cost is one request a day to github.com that the user did not agree to. A found update still needs the user's click. | Leave the key unset. Sparkle then shows a permission prompt on the second launch, and a user who answers "Don't Check" never gets an update prompt. |
| First version with the updater | 0.2.0 | Any version above 0.1.1. |

## Global Constraints

- PR 8 (`feat/app-icon-licences`) is merged before Task 1 starts. This plan edits `macos/build.sh` and `macos/grant_matcher.spec` as that pull request leaves them.
- All work is on one branch, `feat/in-app-updates`, cut from `main`.
- Run every command from `NIH Extractor/` unless the step names the repository root. Run every `git` command from the repository root.
- The test command is `uv run --locked pytest -q`. CI adds `-W error::DeprecationWarning`. Run that form before the push.
- Do not change `streamlit_app.py`. In `nih_grant_matcher/`, change only the `__version__` line, in Task 6.
- Add no Python dependency. `pyproject.toml` and `uv.lock` change only in Task 6, for the version.
- The tests run on Linux in CI, on Python 3.11, 3.13 and 3.15, with no `webview`, no `objc`, no display and no `lsof`. A new test must pass there. `tests/test_macos_launcher.py` already loads the launcher with `webview` and `streamlit` blocked. Keep that.
- `macos/build.sh` runs under bash 3.2 in CI and bash 5 on a developer's Mac. Test every script change with `/bin/bash`. No `mapfile`, and no expansion of an empty array under `set -u`.
- A failed command inside an `EXIT` trap fails the script under bash 3.2. End each such command with `|| true`.
- Under bash 3.2, a `[[ … ]]` that stands alone does not stop a script that runs with `set -e`. Write every check as `[ … ] || { echo "<what failed>" >&2; exit 1; }`. This was reproduced on 2026-11-23.
- On macOS, `wc -c` pads its output with spaces. Take a file's size as `$(($(wc -c < "$file")))`.
- Every new script is committed executable. After `git add`, `git ls-files -s <script>` must show mode `100755`.
- Match the dense style of the existing code. Do not reformat a line that a task does not name. A comment gives a non-obvious reason in one line.
- In a workflow, pin every action to a commit with its tag in a comment, and start every step name with an emoji. Check a workflow change with `actionlint` and `mise x zizmor@1.32.0 -- zizmor .github/workflows`.
- The app stays Apple silicon only, macOS 14.0 or later, hardened runtime, no entitlements, not sandboxed.
- Exact values, used verbatim by the tasks:
  - Sparkle version `2.10.1`
  - Sparkle archive `https://github.com/sparkle-project/Sparkle/releases/download/2.10.1/Sparkle-2.10.1.tar.xz`
  - Sparkle archive SHA-256 `1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27`
  - Feed URL `https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/latest/download/appcast.xml`
  - Download base `https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/download/v<version>`
  - Release asset name `Grant-Matcher-<version>-arm64.dmg`
  - Bundle ID `net.matherly.grant-matcher`, rehearsal bundle ID `net.matherly.gm-rehearsal`
  - Secret name `SPARKLE_ED_KEY`
  - Menu item title `Check for Updates…` (the last character is U+2026)

## Review Focus

These five conditions are the ones most likely to hurt a user and that a unit test alone does not reach. Each names the task that pins it.

1. **The new version's dashboard server does not start.** A bad release would then be the last one a user ever gets, unless the updater runs anyway. Sparkle must start whether or not the server does. Pinned in Task 1 (`test_updater_starts_even_when_the_server_does_not`).
2. **The newest release carries no `appcast.xml`.** GitHub answers the feed URL with a 404. A scheduled check then fails with no message, every day, until a release with a feed is the newest. Version 0.1.1 is in that state now. The release must prove that its own feed is the one installed apps get. Pinned in Task 4 (the last step of the release job) and Task 5 (`--stop-feed`).
3. **The `SPARKLE_ED_KEY` secret does not match the public key in the app.** Every installed app would refuse the update. The release must fail before anything is published. Pinned in Task 3 (`verify-appcast.sh`) and Task 4 (the workflow step).
4. **The app runs from the mounted disk image.** Sparkle cannot replace an app on a read-only volume. The user must be told to move the app, and the app on the image must stay as it is. Pinned in Task 5 (`--from-dmg`).
5. **The update lands while the dashboard server runs.** The server is a child process of the app. After the swap, no process of the old copy may remain, and the relaunched app must have both its processes. Pinned in Task 5 (the default mode).

---

### Task 0: Create the update key (owner)

This task needs the owner's Keychain and GitHub account. An agent stops here and asks.

**Files:**
- Create: `NIH Extractor/macos/sparkle-public-key.txt`

**Interfaces:**
- Produces: `macos/sparkle-public-key.txt`, one line, the base64 public key. Task 2 reads it. The secret `SPARKLE_ED_KEY`, the base64 private seed. Task 4 reads it.

- [ ] **Step 1: Get Sparkle's tools into a private folder**

Run these in one terminal. `$TMPDIR` on macOS is a folder only you can read, and `umask 077` keeps the seed file private.

```bash
umask 077 && mkdir -p "$TMPDIR/sparkle" && cd "$TMPDIR/sparkle"
curl -fsSLO https://github.com/sparkle-project/Sparkle/releases/download/2.10.1/Sparkle-2.10.1.tar.xz
echo "1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27  Sparkle-2.10.1.tar.xz" | shasum -a 256 -c && tar -xJf Sparkle-2.10.1.tar.xz
```

Expected: `Sparkle-2.10.1.tar.xz: OK`, and `bin/generate_keys` exists.

- [ ] **Step 2: Create the key and print its public half**

```bash
bin/generate_keys --account net.matherly.grant-matcher
```

Expected: the Keychain asks for permission, then the tool prints a `SUPublicEDKey` value of 44 characters.

- [ ] **Step 3: Save the public key in the repository**

```bash
bin/generate_keys --account net.matherly.grant-matcher -p > "/Users/jason/dev/Research-Grant-Finder-Agent/NIH Extractor/macos/sparkle-public-key.txt"
```

Expected: `python3 -c "import base64,sys; print(len(base64.b64decode(open(sys.argv[1]).read())))" "/Users/jason/dev/Research-Grant-Finder-Agent/NIH Extractor/macos/sparkle-public-key.txt"` prints `32`.

- [ ] **Step 4: Store the private seed as a secret and in 1Password**

```bash
bin/generate_keys --account net.matherly.grant-matcher -x seed.txt
gh secret set SPARKLE_ED_KEY --repo jrmatherly/Research-Grant-Finder-Agent < seed.txt
```

Copy the contents of `seed.txt` into 1Password, then run `cd ~ && rm -rf "$TMPDIR/sparkle"`.

Expected: `gh secret list --repo jrmatherly/Research-Grant-Finder-Agent` lists `SPARKLE_ED_KEY`.

A lost or leaked seed is replaced by a new key in a release that keeps the same Developer ID certificate. Installed apps accept that one release on the certificate alone.

---

### Task 1: The launcher starts Sparkle and offers a menu item

**Files:**
- Modify: `NIH Extractor/macos/launcher.py`
- Test: `NIH Extractor/tests/test_macos_launcher.py`

**Interfaces:**
- Consumes: `log_path(home: Path) -> Path`, `wait_and_load(window, child, url, log)` and `run_window()` as they exist.
- Produces:
  - `UPDATER: list` at module level. It holds the one `SPUStandardUpdaterController`, so that it is never released.
  - `sparkle_framework() -> Path | None`
  - `start_updater(framework: Path, log: Path) -> None`
  - `check_for_updates() -> None`
  - `app_menu() -> list`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_macos_launcher.py`. `_load` is the existing helper.

```python
def test_no_updater_when_the_app_is_not_frozen(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    assert launcher.sparkle_framework() is None and launcher.app_menu() == []


def test_updater_framework_is_found_inside_the_frozen_bundle(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    framework = tmp_path / "Grant Matcher.app" / "Contents" / "Frameworks" / "Sparkle.framework"
    framework.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Grant Matcher.app" / "Contents" / "MacOS" / "Grant Matcher"))
    assert launcher.sparkle_framework() == framework


def test_frozen_bundle_without_sparkle_has_no_updater(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Contents" / "MacOS" / "Grant Matcher"))
    assert launcher.sparkle_framework() is None


def test_a_failed_updater_start_is_logged_and_never_raised(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    monkeypatch.setitem(sys.modules, "objc", None)
    log = tmp_path / "server.log"
    launcher.start_updater(tmp_path / "Sparkle.framework", log)
    assert launcher.UPDATER == [] and "updater did not start" in log.read_text()


def test_checking_for_updates_without_an_updater_does_nothing(monkeypatch) -> None:
    launcher = _load(monkeypatch)
    launcher.check_for_updates()


def test_updater_starts_even_when_the_server_does_not(monkeypatch, tmp_path) -> None:
    launcher = _load(monkeypatch)
    scheduled = []
    tools = types.ModuleType("PyObjCTools")
    tools.AppHelper = types.SimpleNamespace(callAfter=lambda function, *args: scheduled.append((function, args)))
    monkeypatch.setitem(sys.modules, "PyObjCTools", tools)
    framework, log = tmp_path / "Sparkle.framework", tmp_path / "server.log"
    monkeypatch.setattr(launcher, "sparkle_framework", lambda: framework)
    launcher.wait_and_load(_Window(), _Child(exit_code=1), "http://127.0.0.1:9", log)
    assert scheduled == [(launcher.start_updater, (framework, log))]
```

`_Window`, `_Child` and the `types` import are already in the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_macos_launcher.py`
Expected: six failures. Five are an `AttributeError` on a name from the Interfaces block.

- [ ] **Step 3: Implement the four functions and `UPDATER` in `macos/launcher.py`**

- `sparkle_framework` returns `Path(sys.executable).parent.parent / "Frameworks" / "Sparkle.framework"` when `sys.frozen` is set and that folder exists, else `None`.
- `start_updater` imports `objc` inside the function, then runs these two calls and appends the controller to `UPDATER`:

```python
objc.loadBundle("Sparkle", {}, bundle_path=str(framework))
controller = objc.lookUpClass("SPUStandardUpdaterController").alloc().initWithStartingUpdater_updaterDelegate_userDriverDelegate_(True, None, None)
```

  It catches `Exception`, and appends `f"{NAME} updater did not start:\n{traceback.format_exc()}"` to `log`. It never raises. It must run on the main thread.
- `check_for_updates` returns when `UPDATER` is empty. Otherwise it imports `AppHelper` from `PyObjCTools` and calls `AppHelper.callAfter` with a function that calls `UPDATER[0].checkForUpdates_(None)`. pywebview runs menu actions off the main thread.
- `app_menu` returns `[]` when `sparkle_framework()` is `None`, before it imports anything. Otherwise it imports `Menu` and `MenuAction` from `webview.menu` and returns `[Menu("__app__", [MenuAction("Check for Updates…", check_for_updates)])]`. pywebview puts the items of a menu titled `__app__` into the app menu, between About and Services.

- [ ] **Step 4: Wire both into the window**

- In `wait_and_load`, as its first action and before `start_failure` runs, call `AppHelper.callAfter(start_updater, framework, log)` when `sparkle_framework()` returns a path. The updater must not wait for the server. A release whose server cannot start is the release that most needs an update, and this is Review Focus 1. Import `AppHelper` from `PyObjCTools` inside that branch. pyobjc is not installed on Linux, so an import at the top of the module would fail every CI leg.
- In `run_window`, pass `menu=app_menu()` to `webview.start`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes, six more than before this task.

- [ ] **Step 6: Commit**

```bash
git add "NIH Extractor/macos/launcher.py" "NIH Extractor/tests/test_macos_launcher.py"
git commit -m "feat: start Sparkle from the macOS launcher and add Check for Updates"
```

---

### Task 2: The build embeds and signs Sparkle

**Files:**
- Modify: `NIH Extractor/macos/build.sh`
- Modify: `NIH Extractor/macos/grant_matcher.spec`
- Read: `NIH Extractor/macos/sparkle-public-key.txt` (from Task 0)

**Interfaces:**
- Consumes: `macos/sparkle-public-key.txt`.
- Produces:
  - `macos/build/sparkle/`, the unpacked Sparkle archive, with `bin/sign_update`, `LICENSE` and `Sparkle.framework`. Tasks 3, 4 and 5 use `macos/build/sparkle/bin/sign_update`.
  - An app whose `Info.plist` has `CFBundleVersion`, `SUFeedURL` and `SUPublicEDKey`, and whose `Contents/Frameworks/Sparkle.framework` is signed.
  - Three optional environment variables that the spec reads, for Task 5: `GRANT_MATCHER_VERSION`, `GRANT_MATCHER_BUNDLE_ID`, `SPARKLE_PUBLIC_KEY`. Each replaces the value from `pyproject.toml`, the fixed bundle ID, or the key file.

- [ ] **Step 1: Add the three keys to the spec**

In `grant_matcher.spec`, read the version from `GRANT_MATCHER_VERSION` when it is set, the bundle ID from `GRANT_MATCHER_BUNDLE_ID`, and the public key from `SPARKLE_PUBLIC_KEY` or else from `sparkle-public-key.txt` beside the spec, stripped. Add to `info_plist`:

```python
"CFBundleVersion": version, "SUFeedURL": "https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/latest/download/appcast.xml", "SUPublicEDKey": public_key, "SUEnableAutomaticChecks": True, "SUVerifyUpdateBeforeExtraction": True,
```

- `SUEnableAutomaticChecks` follows the owner's decision at the top of this plan.
- `SUVerifyUpdateBeforeExtraction` makes Sparkle check the EdDSA signature before it mounts a downloaded image. Sparkle reads this key from the installed app, so a later release cannot add it for the users of this one. It must be in the first version that has the updater.
- Do not set `SUAutomaticallyUpdate`. The disk image is over 100 MB, and that key would download it without asking.

- [ ] **Step 2: Fetch the pinned Sparkle in `build.sh`**

Before the PyInstaller line, download the archive to `macos/build/Sparkle-2.10.1.tar.xz` unless it is already there, check it with `shasum -a 256 -c` against the SHA-256 in Global Constraints, and unpack it into `macos/build/sparkle`. Keep the version and the checksum in two variables at the top of the script, `sparkle_version` and `sparkle_sha256`, so that an update changes two lines.

- [ ] **Step 3: Embed and sign Sparkle after PyInstaller, before the smoke test**

Add these lines. The order is the one the spike used, and Sparkle's documentation forbids `--deep` here.

```bash
framework="$app/Contents/Frameworks/Sparkle.framework"
ditto macos/build/sparkle/Sparkle.framework "$framework"
# The XPC services only serve a sandboxed app.
rm -rf "$framework/Versions/B/XPCServices" "$framework/XPCServices"
mkdir -p "$app/Contents/Resources/licenses/sparkle"
cp macos/build/sparkle/LICENSE "$app/Contents/Resources/licenses/sparkle/"
sign=(codesign --force --sign "${CODESIGN_IDENTITY:--}")
# PyInstaller adds the hardened runtime only with a real identity, and an ad hoc build must match it.
if [[ -n ${CODESIGN_IDENTITY:-} ]]; then sign+=(--options runtime --timestamp); fi
"${sign[@]}" "$framework/Versions/B/Autoupdate"
"${sign[@]}" "$framework/Versions/B/Updater.app"
"${sign[@]}" "$framework"
"${sign[@]}" "$app"
```

PyInstaller has already signed the app. The last line signs it again without `--deep`, which seals the new framework and the licence file and leaves the nested signatures as they are.

- [ ] **Step 4: Make the build check what it embedded**

After the existing `test -s` line for the Streamlit notices, add checks that fail the build:

```bash
test -x "$framework/Versions/B/Autoupdate"
test ! -e "$framework/Versions/B/XPCServices"
[ "$(plutil -extract CFBundleVersion raw -o - "$app/Contents/Info.plist")" = "$(plutil -extract CFBundleShortVersionString raw -o - "$app/Contents/Info.plist")" ] || { echo "CFBundleVersion differs from CFBundleShortVersionString" >&2; exit 1; }
# Sparkle orders "0.2.0-rc1" as equal to "0.2.0" and "0.2.0rc1" as older, so only plain numbers are allowed.
plutil -extract CFBundleVersion raw -o - "$app/Contents/Info.plist" | grep -Eq '^[0-9]+(\.[0-9]+){0,2}$' || { echo "CFBundleVersion is not one to three numbers" >&2; exit 1; }
[ "$(($(plutil -extract SUPublicEDKey raw -o - "$app/Contents/Info.plist" | base64 --decode | wc -c)))" = 32 ] || { echo "SUPublicEDKey is not a 32-byte key" >&2; exit 1; }
```

Change the existing `codesign --verify --deep --strict` so that it runs with and without `CODESIGN_IDENTITY`.

- [ ] **Step 5: Build signed, under bash 3.2, and verify**

Run: `shellcheck macos/build.sh`
Expected: no output.

Run: `CODESIGN_IDENTITY="Developer ID Application: Jason Matherly (7BSA2L4Z5L)" /bin/bash macos/build.sh; echo "exit $?"`
Expected: `Sparkle-2.10.1.tar.xz: OK`, `Smoke test passed`, `valid on disk`, and `exit 0`.

Run: `codesign -dvv "macos/dist/Grant Matcher.app/Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate" 2>&1 | grep -E 'TeamIdentifier|Timestamp|flags'`
Expected: `TeamIdentifier=7BSA2L4Z5L`, a `Timestamp=` line, and `flags=0x10000(runtime)`.

- [ ] **Step 6: Build without an identity and verify**

Run: `/bin/bash macos/build.sh; echo "exit $?"`
Expected: `exit 0`. This is the first build of the unsigned path that anyone has run.

- [ ] **Step 7: Launch the signed build and look**

Run: `open "macos/dist/Grant Matcher.app"`, then open the app menu.
Expected: `Check for Updates…` sits between About and Services. Choosing it shows a Sparkle window. No release carries a feed yet, so that window reports that it cannot get the feed. This is Review Focus 1. The dashboard behind it still works. Quit, then run `pgrep -f "Contents/MacOS/Grant Matcher"`.
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add "NIH Extractor/macos/build.sh" "NIH Extractor/macos/grant_matcher.spec" "NIH Extractor/macos/sparkle-public-key.txt"
git commit -m "feat: embed and sign Sparkle in the macOS app"
```

---

### Task 3: Write and check the appcast

**Files:**
- Create: `NIH Extractor/macos/make-appcast.sh`
- Create: `NIH Extractor/macos/verify-appcast.sh`
- Create: `NIH Extractor/macos/verify-signature.swift`
- Test: `NIH Extractor/tests/test_macos_appcast.py`

**Interfaces:**
- Consumes: `macos/build/sparkle/bin/sign_update` from Task 2.
- Produces:
  - `macos/make-appcast.sh <dmg> <version>` prints the feed on standard output. It reads `SPARKLE_ED_KEY`. `SIGN_UPDATE` replaces the path of `sign_update`. `APPCAST_DOWNLOAD_BASE` replaces the download base. The enclosure's file name is the base name of `<dmg>`.
  - `macos/verify-appcast.sh <app> <dmg> <appcast>` exits 0 when the feed is well formed, its `length` equals the size of `<dmg>`, and the public key in `<app>` accepts its signature. It needs no secret.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_macos_appcast.py`. The tests run the script with a stand-in for `sign_update`, so they pass on Linux.

```python
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "macos" / "make-appcast.sh"
SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"


def _run(tmp_path, env=None, dmg_exists=True):
    signer = tmp_path / "sign_update"
    # Prints a fixed signature, and succeeds on --verify.
    signer.write_text('#!/bin/bash\ncat > /dev/null\nfor a in "$@"; do [ "$a" = --verify ] && exit 0; done\necho "c2lnbmF0dXJl"\n')
    signer.chmod(0o755)
    dmg = tmp_path / "Grant-Matcher-1.2.3-arm64.dmg"
    if dmg_exists:
        dmg.write_bytes(b"x" * 1234)
    full = {**os.environ, "SPARKLE_ED_KEY": "c2VlZA==", "SIGN_UPDATE": str(signer), **(env or {})}
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


def test_download_base_can_be_replaced(tmp_path) -> None:
    result = _run(tmp_path, env={"APPCAST_DOWNLOAD_BASE": "http://127.0.0.1:8811"})
    assert ET.fromstring(result.stdout).find("channel/item/enclosure").get("url") == "http://127.0.0.1:8811/Grant-Matcher-1.2.3-arm64.dmg"


def test_no_appcast_without_the_key(tmp_path) -> None:
    result = _run(tmp_path, env={"SPARKLE_ED_KEY": ""})
    assert result.returncode != 0 and result.stdout == "" and "SPARKLE_ED_KEY" in result.stderr


def test_no_appcast_for_a_missing_disk_image(tmp_path) -> None:
    result = _run(tmp_path, dmg_exists=False)
    assert result.returncode != 0 and result.stdout == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --locked pytest -q tests/test_macos_appcast.py`
Expected: five failures, because the script does not exist.

- [ ] **Step 3: Write `macos/make-appcast.sh`**

`set -euo pipefail`, bash 3.2, clean under `shellcheck`. It refuses to run without `SPARKLE_ED_KEY` or without the disk image, each with a message on standard error that names what is missing. It feeds the key to `sign_update` on standard input, never as an argument:

```bash
signature=$(printf '%s' "$SPARKLE_ED_KEY" | "$sign_update" --ed-key-file - -p "$dmg")
printf '%s' "$SPARKLE_ED_KEY" | "$sign_update" --verify --ed-key-file - "$dmg" "$signature" > /dev/null
```

It takes the length as `length=$(($(wc -c < "$dmg")))`, which gives a bare number on macOS and Linux. It prints nothing on standard output until every check has passed. The feed has one item:

```xml
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>Grant Matcher</title>
    <item>
      <title>$version</title>
      <sparkle:version>$version</sparkle:version>
      <sparkle:shortVersionString>$version</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>14.0.0</sparkle:minimumSystemVersion>
      <sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>
      <description sparkle:format="markdown"><![CDATA[Grant Matcher $version. [Release notes](https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/tag/v$version)]]></description>
      <enclosure url="$base/$(basename "$dmg")" length="$length" type="application/octet-stream" sparkle:edSignature="$signature"/>
    </item>
  </channel>
</rss>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --locked pytest -q tests/test_macos_appcast.py && shellcheck macos/make-appcast.sh`
Expected: `5 passed`, and no output from `shellcheck`.

- [ ] **Step 5: Write `macos/verify-signature.swift` and `macos/verify-appcast.sh`**

`verify-signature.swift` is this file. It was run against the spike's disk image on 2026-11-23, where it exited 0 for the signed file and 1 for another file.

```swift
import CryptoKit
import Foundation
let a = CommandLine.arguments
let key = try Curve25519.Signing.PublicKey(rawRepresentation: Data(base64Encoded: a[1])!)
let data = try Data(contentsOf: URL(fileURLWithPath: a[3]))
exit(key.isValidSignature(Data(base64Encoded: a[2])!, for: data) ? 0 : 1)
```

`verify-appcast.sh` runs `xmllint --noout` on the feed. It reads an attribute of the enclosure with `xmllint --xpath "string(//*[local-name()='enclosure']/@*[local-name()='edSignature'])"`, and `length` the same way, because `sparkle:edSignature` is in a namespace. It compares `length` with `$(($(wc -c < "$dmg")))`, reads `SUPublicEDKey` from the app with `plutil -extract SUPublicEDKey raw -o -`, and runs `swift macos/verify-signature.swift <public key> <signature> <dmg>`. Each failed check prints one line on standard error that says which check failed, and exits 1.

- [ ] **Step 6: Prove that a wrong key is caught**

This step is Review Focus 3. Make two throwaway keys without the Keychain:

```bash
keypair() { swift -e 'import CryptoKit
let k = Curve25519.Signing.PrivateKey()
print(k.rawRepresentation.base64EncodedString())
print(k.publicKey.rawRepresentation.base64EncodedString())'; }
```

Build the app with `SPARKLE_PUBLIC_KEY` set to the public half of the first key. Write one feed with the first seed and one with the second seed, each through `make-appcast.sh` on `macos/dist/Grant Matcher.dmg`.

Run: `macos/verify-appcast.sh "macos/dist/Grant Matcher.app" "macos/dist/Grant Matcher.dmg" <first feed>; echo $?`
Expected: `0`.

Run the same command on the second feed.
Expected: a line that names the signature check, then `1`.

- [ ] **Step 7: Commit**

```bash
chmod +x "NIH Extractor/macos/make-appcast.sh" "NIH Extractor/macos/verify-appcast.sh"
git add "NIH Extractor/macos/make-appcast.sh" "NIH Extractor/macos/verify-appcast.sh" "NIH Extractor/macos/verify-signature.swift" "NIH Extractor/tests/test_macos_appcast.py"
git ls-files -s "NIH Extractor/macos/make-appcast.sh" "NIH Extractor/macos/verify-appcast.sh"
git commit -m "feat: write and check the update feed for a macOS release"
```

Expected from `git ls-files -s`: both lines start with `100755`. The workflow runs these scripts by path, and the tests would not notice a missing mode, because they call `/bin/bash <script>`.

---

### Task 4: The release publishes the feed

**Files:**
- Modify: `.github/workflows/macos-release.yml`
- Modify: `docs/macos-app.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: `macos/make-appcast.sh` and `macos/verify-appcast.sh` from Task 3, and the secret `SPARKLE_ED_KEY` from Task 0.
- Produces: a release with three assets, `Grant-Matcher-<version>-arm64.dmg`, its `.sha256` file, and `appcast.xml`.

- [ ] **Step 1: Require the sixth secret**

In the step `🔎 Check the tag, the version and the release secrets`, add `&& secrets.SPARKLE_ED_KEY != ''` to `HAS_SECRETS`, and name `SPARKLE_ED_KEY` in the error message.

- [ ] **Step 2: Write and check the feed after the asset is named**

Add one step after `📦 Name the disk image and write its checksum`. The signature covers the bytes of the file, so the feed is written from the renamed copy, whose name is the name in the enclosure URL.

```yaml
      - name: "📰 Write and check the update feed"
        env:
          SPARKLE_ED_KEY: ${{ secrets.SPARKLE_ED_KEY }}
        run: |
          asset="$RUNNER_TEMP/release/Grant-Matcher-$VERSION-arm64.dmg"
          macos/make-appcast.sh "$asset" "$VERSION" > "$RUNNER_TEMP/release/appcast.xml"
          # A wrong SPARKLE_ED_KEY stops here, because every installed app would refuse the update.
          macos/verify-appcast.sh "macos/dist/Grant Matcher.app" "$asset" "$RUNNER_TEMP/release/appcast.xml"
```

The upload and release steps already take every file in that folder, so they need no change.

- [ ] **Step 3: Make the release job prove that installed apps see the release**

Add one step at the end of the `release` job. `gh release create` makes a draft, uploads the assets, and then publishes, so the feed exists when the release becomes the newest. This step catches the other cases, such as a newer release that carries no feed.

```yaml
      - name: "🔎 Check that installed apps can see the release"
        env:
          GH_REPO: ${{ github.repository }}
          TAG: ${{ github.ref_name }}
        run: |
          feed="https://github.com/$GH_REPO/releases/latest/download/appcast.xml"
          for _ in 1 2 3 4 5 6; do
            if curl -fsSL "$feed" | grep -qF "<sparkle:version>${TAG#v}</sparkle:version>"; then exit 0; fi
            sleep 10
          done
          echo "::error::$feed does not offer ${TAG#v}. Installed apps will not see this release."
          exit 1
```

- [ ] **Step 4: Lint the workflow**

Run, from the repository root: `actionlint .github/workflows/macos-release.yml && mise x zizmor@1.32.0 -- zizmor .github/workflows`
Expected: `No findings to report.`

- [ ] **Step 5: Document updates**

In `docs/macos-app.md`:
- Add a section `## Updates` after `## Download`. It says that the app checks for a new release once a day, that `Check for Updates…` in the app menu checks at once, that an update needs the app to be in a folder it can write to and not on the disk image, and that version 0.1.1 has no updater, so its users install the next version by hand once.
- In `## Publish a release`, add `SPARKLE_ED_KEY` to the table of secrets, with the contents "The private seed of the Sparkle update key, base64. A copy is in 1Password." Change "five" to "six", and add `appcast.xml` to the list of what the release carries.
- In `## Licences and the icon`, add one sentence. The build downloads Sparkle 2.10.1 and checks it against the checksum in `build.sh`.

- In `## Publish a release`, add two rules. A release that carries no `appcast.xml` must not become the newest release, so create it with `gh release create --latest=false` or as a pre-release. To withdraw a bad release, mark it as a pre-release, and the feed falls back to the release before it.

In `AGENTS.md`, extend the `macos-release.yml` bullet. It needs six secrets, and it publishes `appcast.xml`, which installed apps read from the newest release that is not a pre-release.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/macos-release.yml docs/macos-app.md AGENTS.md
git commit -m "feat: publish the update feed with each macOS release"
```

---

### Task 5: Rehearse a real update

**Files:**
- Create: `NIH Extractor/macos/rehearse-update.sh`

**Interfaces:**
- Consumes: `macos/build.sh` with the three environment variables from Task 2, `macos/make-appcast.sh` with `APPCAST_DOWNLOAD_BASE`, and `macos/verify-appcast.sh`.
- Produces: `macos/rehearse-update.sh [--bad-signature | --stop-feed | --from-dmg]`. It exits 0 when the outcome matches the mode.

- [ ] **Step 1: Write `macos/rehearse-update.sh`**

It follows `scripts/rehearse-update.sh` in `claude-multipass`. It is bash 3.2 and clean under `shellcheck`. It does this:

1. Stops with a message unless `CODESIGN_IDENTITY` is set. An update between two ad hoc builds is unproven.
2. Unsets `NOTARY_PROFILE`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID` and `APPLE_API_KEY_P8`. With one of them set, `build.sh` would send both throwaway builds to Apple.
3. Makes a throwaway key pair with the `keypair` function from Task 3, Step 6. The real key and the Keychain are not used.
4. Builds version 0.0.1 with `GRANT_MATCHER_VERSION=0.0.1`, `GRANT_MATCHER_BUNDLE_ID=net.matherly.gm-rehearsal` and `SPARKLE_PUBLIC_KEY` set to the throwaway public key. It copies the app to `$work/install/` and the disk image to `$work/old.dmg` before the next build, because `build.sh` writes both builds to the same paths in `macos/dist`.
5. Builds version 0.0.2 the same way, and copies its disk image to `$work/feed/Grant-Matcher-0.0.2-arm64.dmg`. The name has no space, so the enclosure URL needs no encoding.
6. Writes the feed with `make-appcast.sh` on that copy, with `APPCAST_DOWNLOAD_BASE=http://127.0.0.1:<port>`. In `--bad-signature` mode it signs with a second throwaway seed. In every other mode it then runs `verify-appcast.sh` on the installed app, the copy and the feed.
7. Serves the feed folder with `python3 -m http.server` on a free port, and waits up to 10 seconds for `curl` to get `appcast.xml`. In `--stop-feed` mode it serves nothing.
8. Notes the contents of `~/Library/LaunchAgents`, then runs `defaults write net.matherly.gm-rehearsal SUFeedURL http://127.0.0.1:<port>/appcast.xml`. Sparkle reads this default in place of the key in `Info.plist`.
9. Opens the 0.0.1 app from `$work/install/`. In `--from-dmg` mode it mounts `$work/old.dmg` read-only and opens the app on it.
10. Prints what the person must click, which is `Check for Updates…`, then `Install Update`, then `Install and Relaunch`. It waits up to `REHEARSE_SECONDS`, 180 by default.
11. Finds its own processes with `pgrep -f "$app_path/Contents/MacOS/Grant Matcher"`, where `$app_path` is the full path of the copy it opened. A shorter pattern would also match a real Grant Matcher that is running.
12. In the default mode it exits 0 only when all of these hold. `CFBundleShortVersionString` of the installed app reads `0.0.2`. Two processes of that copy are running within 30 seconds, the window and the server. `codesign --verify --deep --strict` passes on it. Within 30 seconds, `launchctl print gui/$(id -u)` shows no job whose name holds `gm-rehearsal-sparkle`. `~/Library/LaunchAgents` holds what it held before.
13. In each other mode it exits 0 only when the app it opened still reads `0.0.1` at the deadline.
14. On exit, in a trap whose commands each end with `|| true`, it stops its own processes and the server, detaches the image, runs `defaults delete net.matherly.gm-rehearsal`, and removes `$work`, `macos/dist/Grant Matcher.app`, `macos/dist/Grant Matcher.dmg`, `~/Library/Caches/net.matherly.gm-rehearsal`, `~/Library/HTTPStorages/net.matherly.gm-rehearsal` and `~/Library/Preferences/net.matherly.gm-rehearsal.plist`.

The rehearsal app keeps the name Grant Matcher, so it uses the real `~/Library/Application Support/Grant Matcher` and `~/Library/Logs/Grant Matcher`. It reads the database there. Each launch rotates `server.log`, so the two launches of a rehearsal push the real app's last log out of both files. The script says both things when it starts, and it removes the builds in `macos/dist` when it ends.

- [ ] **Step 2: Run the default mode**

Run: `CODESIGN_IDENTITY="Developer ID Application: Jason Matherly (7BSA2L4Z5L)" /bin/bash macos/rehearse-update.sh`, and click through the three prompts.
Expected: a final line that reports the update to 0.0.2 and the relaunch, and exit 0. This is Review Focus 5.

- [ ] **Step 3: Run the three failure modes**

Run the script with `--bad-signature`, then `--stop-feed`, then `--from-dmg`. In each, choose `Check for Updates…`.
Expected, in order. Sparkle reports that the update is improperly signed. Sparkle reports that it cannot reach the feed, and the app opened with no alert before the check. Sparkle tells the user to move the app. Each run exits 0 with the installed app at 0.0.1. These are Review Focus 3, 1 and 2.

- [ ] **Step 4: Record the evidence**

Save a screenshot of each of the four Sparkle windows under `docs/superpowers/plans/2026-11-23-in-app-updates-evidence/`, named `happy.png`, `bad-signature.png`, `stop-feed.png` and `from-dmg.png`.

- [ ] **Step 5: Commit**

```bash
chmod +x "NIH Extractor/macos/rehearse-update.sh"
git add "NIH Extractor/macos/rehearse-update.sh" docs/superpowers/plans/2026-11-23-in-app-updates-evidence
git commit -m "test: rehearse a real in-app update of the macOS app"
```

---

### Task 6: Release the first build with the updater, and prove an update (owner)

A push, a merge and a tag each need the owner's word. An agent asks before each.

**Files:**
- Modify: `NIH Extractor/pyproject.toml`
- Modify: `NIH Extractor/nih_grant_matcher/__init__.py`
- Modify: `NIH Extractor/uv.lock`

- [ ] **Step 1: Set the version to 0.2.0**

Set `version = "0.2.0"` in `pyproject.toml` and `__version__ = "0.2.0"` in `nih_grant_matcher/__init__.py`, then run `uv lock`. That line is the plan's only edit to the package.

Run: `uv run --locked pytest -q -W error::DeprecationWarning`
Expected: every test passes.

- [ ] **Step 2: Open the pull request, and merge it when CI is green**

Push `feat/in-app-updates`, open a pull request against `main` of `jrmatherly/Research-Grant-Finder-Agent`, and merge by rebase after `✅ Required checks passed`.

- [ ] **Step 3: Tag and watch the release**

A rebase merge gives the commits new hashes, and the workflow refuses a tag that is not on `main`. Tag the merged commit, not the branch.

```bash
git switch main && git pull --ff-only
git tag -a v0.2.0 -m "Grant Matcher 0.2.0" && git push origin v0.2.0
```

Expected: the `🍎 macOS app` run passes. This is the first time Apple notarizes a build that holds Sparkle.

- [ ] **Step 4: Check the published release**

Run: `gh release view v0.2.0 --repo jrmatherly/Research-Grant-Finder-Agent --json assets -q '.assets[].name'`
Expected: `Grant-Matcher-0.2.0-arm64.dmg`, `Grant-Matcher-0.2.0-arm64.dmg.sha256`, `appcast.xml`.

Run: `curl -fsSL https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/latest/download/appcast.xml | grep -c '<sparkle:version>0.2.0</sparkle:version>'`
Expected: `1`.

Download the disk image and run `xcrun stapler validate` and `spctl -a -t open --context context:primary-signature -vv` on it.
Expected: `The validate action worked!` and `source=Notarized Developer ID`.

- [ ] **Step 5: Install 0.2.0 and check for updates**

Drag the app from the disk image to `/Applications`, open it, and choose `Check for Updates…`.
Expected: Sparkle says that 0.2.0 is the newest version.

- [ ] **Step 6: Release 0.2.1 and update to it from 0.2.0**

The rehearsal used a local feed over plain HTTP. Only a second published release proves the real path, which is GitHub's redirect, a notarized image and the real key. Repeat Steps 1 to 4 with version 0.2.1. A release with no other change is enough.

With 0.2.0 still installed in `/Applications`, choose `Check for Updates…`.
Expected: the prompt offers 0.2.1. After `Install Update` and `Install and Relaunch`, the About window shows 0.2.1. Record the result in `.remember/remember.md`.

---

## Appendix A. Spec: findings, the spike, and the decisions

### What the owner asked for

An installed app must check for new releases and apply them, to simplify updating. The request named `claude-multipass` and `llm-router` as sources to draw on.

### What the reference projects do

- `claude-multipass` is a Swift app built with SwiftPM. It uses Sparkle 2.10.1 for installs from the disk image, and the package manager for cask installs. It removes Sparkle's XPC services, signs `Autoupdate`, then `Updater.app`, then the framework, then the app, and never uses `--deep`. It writes its feed by hand in `scripts/make-appcast.sh` with `sign_update --ed-key-file -`, checks it in `scripts/verify-appcast.sh`, and rehearses a real update in `scripts/rehearse-update.sh`. Its feed is a file in the `homebrew-tap` repository.
- `llm-router` is an Electron app. It uses `electron-updater`, which does not apply to a Python app.
- `claude-multipass` recorded three lessons. The private seed cannot be read back from GitHub, so it is kept in 1Password. An app run from the mounted disk image cannot update. A feed on `raw.githubusercontent.com` is cached for 300 seconds.

### What the spike proved

On 2026-11-23, on macOS 27.2.1 and Apple silicon, two throwaway builds of the real app (0.0.1 and 0.0.2, bundle ID `net.matherly.gm-rehearsal`, a throwaway key) ran a full update against a local feed.

| Question | Result |
| --- | --- |
| Can pyobjc load Sparkle 2.10.1 inside a PyInstaller bundle? | Yes. `objc.loadBundle` and `SPUStandardUpdaterController` worked, and the updater reported the feed and `canCheckForUpdates` as true. |
| Does the menu item appear? | Yes, between About and Services, through pywebview's `__app__` menu. |
| Does Sparkle's standard window work? | Yes. It showed the app icon and the Markdown release notes. |
| Does Sparkle 2.10.1 open a `.dmg` on macOS 27.2? | Yes. It reached "Ready to Install". |
| Does the swap work with the server child running? | Yes. The app on disk read 0.0.2 one second after the click, and both processes came back. |
| Is the result sound? | `codesign --verify --deep --strict` passed, the dashboard server answered, Quit left no process, and no Sparkle launchd job remained. |
| Does the bundle verify after the framework is added and the app is signed again without `--deep`? | Yes. |
| Does Sparkle follow a redirect to the feed? | Yes, for a 302 on a local server. GitHub answers `releases/latest/download/<asset>` with a 302. |

The spike's files are in the session scratchpad and are not part of the repository.

### Facts from the documentation

- Sparkle 2.10.1 was published on 2026-10-25, needs macOS 12 or later, and has the MIT licence.
- A build outside Xcode needs `CFBundleVersion`, `CFBundleShortVersionString`, `SUFeedURL`, `SUPublicEDKey` and `LSMinimumSystemVersion`. Sparkle compares `CFBundleVersion`. The app set only the short version before this plan.
- With `SUEnableAutomaticChecks` unset, Sparkle shows a permission prompt on the second launch, and "Don't Check" turns scheduled checks off for good. With the key set to `true`, it checks without asking. The check interval defaults to one day.
- A scheduled check that fails shows nothing. A check the user starts shows the error. A 404 at the feed URL is such a failure.
- `SUVerifyUpdateBeforeExtraction` makes Sparkle verify the EdDSA signature before it opens the archive. It is read from the installed app.
- Sparkle's version comparator orders `0.2.0` below `0.10.0`, and `0.2.0rc1` below `0.2.0`. It treats `0.2.0-rc1` as equal to `0.2.0`. A reviewer ran these against the 2.10.1 framework on 2026-11-23.
- The XPC services and the keys that enable them are for a sandboxed app only.
- Sparkle accepts a `.dmg`. It finds the app inside by name, then by bundle ID, and skips symlinks, so the link to `/Applications` on the image does no harm.
- When the old and the new app hold the same public key, Sparkle refuses an update whose EdDSA signature is wrong, even if the Developer ID matches. When the new app holds a different key, a matching Developer ID is enough, which is how a lost key is replaced.
- `gh release create` with assets makes a draft, uploads each asset, and then publishes. Its own help text says so.
- Before it swaps the app, Sparkle refuses a downgrade, releases the new copy from quarantine, and runs a Gatekeeper scan on macOS 14.4 and later.
- `generate_keys` keeps the private key in the login Keychain. Its help says one key serves every app.

### Options rejected

| Option | Why it lost |
| --- | --- |
| A check of the GitHub Releases API that only notifies | It does not apply the update. The user still downloads and drags the app. |
| A hand-written updater | It would have to redo Sparkle's work, which is the signature and team check, the quarantine release, the atomic swap with rollback, and the prompt when the folder needs an administrator. |
| A Python update library | PyUpdater and esky are archived. tufup's documentation does not cover a signed `.app` bundle. |
| `electron-updater`, as in `llm-router` | It is for Electron only. |
| Letting PyInstaller collect and sign the framework | PyInstaller signs with `--deep`, which Sparkle's documentation warns against. The copy after PyInstaller is the path the spike proved. |
| `generate_appcast` | It manages a folder of archives and a history. The feed needs one item, and a hand-written feed is what `claude-multipass` maintains. |

## Appendix B. Risks and what stays unproven

| Risk | Where it shows | What settles it |
| --- | --- | --- |
| Apple has never notarized this app with Sparkle inside. | Task 6, Step 3 | The release run. `claude-multipass` notarizes the same layout. |
| Only macOS 27.2 was tested. Sparkle has a pending change for mounting disk images on 27.2 and later. | Task 5 | A rehearsal on a Mac with macOS 14 or 15, if one is at hand. |
| A newer release with no `appcast.xml` silences every installed app's scheduled check. The orphan tag `v0.1.0` would do this if someone made a release of it. | Any later release | The last step of the release job, and the two rules in `docs/macos-app.md`. |
| `SUVerifyUpdateBeforeExtraction` was not set in the spike. | Task 5 | The rehearsal's default mode, which runs with the key set. |
| The ad hoc build has never been run, with or without Sparkle. | Task 2, Step 6 | That step. If the ad hoc app does not launch, stop and report. Do not add the hardened runtime to it. |
| An update of a release whose server cannot start is covered by a unit test only. | Task 1 | A rehearsal mode with a broken server, if the owner wants more proof. |
| A user who installed to `/Applications` without administrator rights gets a password prompt from Sparkle. | Not tested | A manual check on such an account. |
| Sparkle is pinned by hand. Renovate cannot compute the new checksum. | `macos/build.sh` | A person changes `sparkle_version` and `sparkle_sha256` together, then runs Task 5. |
| The rehearsal app shares the real app's data and log folders. | Task 5 | The script says so at the start. It reads the database and rotates the log. |
| Users of 0.1.1 get no prompt. | After Task 6 | The release notes of 0.2.0 say to install it by hand once. |

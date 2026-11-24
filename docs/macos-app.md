# Build NIH Grant Matcher as a macOS app

`Grant Matcher.app` shows the dashboard in its own window. It starts the dashboard server on a free port on `127.0.0.1` and stops it when you quit.

## Download

Each release on the [releases page](https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases) carries `Grant-Matcher-<version>-arm64.dmg`, signed with a Developer ID certificate and notarized by Apple, and a `.sha256` file to check it against. It needs a Mac with Apple silicon and macOS 14 or later. Open the disk image and drag `Grant Matcher` to `Applications`.

## Updates

The app checks for a new release once a day and offers to install it. `Check for Updates…` in the `Grant Matcher` menu checks at once. An update replaces the app where it is, so the app must be in a folder it can write to, such as `Applications`, and not on the disk image.

Version 0.1.1 has no updater. Install the next version by hand once, as in [Download](#download).

The rest of this page is for building the app yourself with `NIH Extractor/macos/build.sh`.

## Before you begin

- A Mac with Apple silicon and macOS 14 or later. The build makes an `arm64` app only.
- The Xcode command line tools, or Xcode. `xcode-select -p` prints their folder when they are installed.
- [uv](https://docs.astral.sh/uv/). The build installs PyInstaller and pywebview from the `macos` dependency group in `pyproject.toml`. `uv sync` without `--group macos` does not install them. The build runs on uv's own Python and downloads it when it is missing, because the app reads its CA certificates from the file that Python was built to read. A project environment made from another Python is replaced.

## Build

From the repository root:

```bash
"NIH Extractor/macos/build.sh"
```

Without a signing identity, the build signs the app ad hoc. It runs on the Mac that built it.

To sign with your Developer ID certificate, set `CODESIGN_IDENTITY` to its name. `security find-identity -v -p codesigning` lists the names.

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" "NIH Extractor/macos/build.sh"
```

The build takes a few minutes. It then starts the server from the built app and fails if the dashboard script does not run cleanly within 30 seconds. It checks the app's signature and the update settings in its `Info.plist`. With `CODESIGN_IDENTITY` set, it also signs the disk image.

The results are in `NIH Extractor/macos/dist`:

| File | Contents |
| --- | --- |
| `Grant Matcher.app` | The app. Drag it to `/Applications`, or open it where it is. |
| `Grant Matcher.dmg` | A disk image that holds the app and a link to `/Applications`. |

Git ignores `NIH Extractor/macos/build` and `NIH Extractor/macos/dist`.

## Where the app keeps its files

| Folder | Contents |
| --- | --- |
| `~/Library/Application Support/Grant Matcher` | The database `data/grants.sqlite3` and the Excel files in `outputs/`. The dashboard writes them here in place of `NIH Extractor/`. |
| `~/Library/Logs/Grant Matcher/server.log` | The dashboard server's output from the last launch, with the launch before it in `server.log.1`. Read it when the window says the server could not start. |

The app does not read the database in your clone. To keep earlier results, copy `NIH Extractor/data/grants.sqlite3` to `~/Library/Application Support/Grant Matcher/data/`.

## Where the app keeps a model's key

A key you save in the Apply view's **Model** section goes to your login Keychain, as a password item whose service is `Grant Matcher` and whose account is the provider's name: `claude`, `openai`, `gemini` or `compatible`. Grant Matcher writes and reads it with `/usr/bin/security`, so an update of the app does not lock you out of it.

The key is encrypted at rest and locked while the login keychain is locked, and it does not travel with a copy or a backup of the data folder. Any program that runs as you can still read it with `security`. `security find-generic-password -s "Grant Matcher" -a claude` shows the item without the key. **Remove the saved key** in the dashboard deletes it. A locked keychain, or a declined or cancelled Keychain prompt, gives a red message and is never taken for a missing key. Grant Matcher asks the Keychain once and keeps the answer, so unlock the keychain, then select **Try again** under the message.

## Licences and the icon

The app carries the licence texts of the packages it bundles, in `Grant Matcher.app/Contents/Resources/licenses`, one folder per package. The build copies them from the installed packages. Streamlit's package holds none, so the build fetches Streamlit's `LICENSE` and `NOTICES` files for the installed version from its repository and checks them against `NIH Extractor/macos/streamlit-licenses.sha256`. When a new Streamlit changes either file, the build stops and names the folder to read. Update the checksums with `shasum -a 256 LICENSE NOTICES` in that folder.

The updater is [Sparkle](https://sparkle-project.org). The build downloads Sparkle 2.10.1 and checks it against the checksum in `build.sh`. To move to a newer Sparkle, change `sparkle_version` and `sparkle_sha256` there together, then run `NIH Extractor/macos/rehearse-update.sh`.

The rehearsal updates a throwaway version 0.0.1 to 0.0.2 with a key of its own. It needs `CODESIGN_IDENTITY`, and someone to choose `Check for Updates…`, then `Install Update`, then `Install and Relaunch`. Its app is also named Grant Matcher, so it reads the real database and rotates the real `server.log`. When it ends, it deletes `Grant Matcher.app` and `Grant Matcher.dmg` from `NIH Extractor/macos/dist`.

The icon is `NIH Extractor/macos/icon.png`, a 1024-pixel render of `icon.svg` beside it. After a change to the SVG, render it again with a browser, for example:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars --force-device-scale-factor=1 --window-size=1024,1024 --default-background-color=00000000 --screenshot="$PWD/NIH Extractor/macos/icon.png" "file://$PWD/NIH Extractor/macos/icon.svg"
```

## Notarize

A Mac blocks an app that arrives from another computer unless Apple has notarized it. A build you run on the Mac that made it does not need this step.

The build notarizes the `.dmg` and staples the ticket to it when `CODESIGN_IDENTITY` is set together with one of these:

- `NOTARY_PROFILE`, the name of a keychain profile made with `xcrun notarytool store-credentials`.
- `APPLE_API_KEY_P8`, `APPLE_API_KEY_ID` and `APPLE_API_ISSUER_ID`, an App Store Connect API key. The release workflow uses these.

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" NOTARY_PROFILE=grant-matcher "NIH Extractor/macos/build.sh"
```

The notarization step has run only in the release workflow, not on a developer's Mac.

Use a Developer ID Application certificate issued by the Developer ID G2 Sub-CA. The older Developer ID Certification Authority expires on 2027-02-01, and the certificates it issued expire with it. `security find-certificate -c "Developer ID Application" -p | openssl x509 -noout -issuer -enddate` shows the issuer and the end date of your certificate.

## Publish a release

`.github/workflows/macos-release.yml` runs on a `v*` tag. It builds, signs and notarizes the disk image on an Apple silicon runner, then attaches `Grant-Matcher-<version>-arm64.dmg`, its checksum and the update feed `appcast.xml` to the tag's GitHub release. Installed apps read the feed from the newest release that is not a pre-release. The same tag also publishes the Docker image.

The workflow stops before it builds when the tag does not equal `v` plus the `version` in `NIH Extractor/pyproject.toml`, when the tagged commit is not on `main`, or when a secret is missing. It never replaces an asset on an existing release.

The repository needs six Actions secrets:

| Secret | Contents |
| --- | --- |
| `MACOS_CERT_P12` | The Developer ID Application certificate and its private key, exported as a `.p12` file and base64-encoded |
| `MACOS_CERT_PASSWORD` | The password set when the `.p12` file was exported |
| `APPLE_API_KEY_ID` | The Key ID of an App Store Connect API key |
| `APPLE_API_ISSUER_ID` | The Issuer ID shown above the keys in App Store Connect |
| `APPLE_API_KEY_P8` | The text of the key's `AuthKey_<Key ID>.p8` file |
| `SPARKLE_ED_KEY` | The private seed of the Sparkle update key, base64. A copy is in 1Password. |

The public half of that key is `NIH Extractor/macos/sparkle-public-key.txt`, which the build writes into the app. The workflow stops before it publishes when the secret does not match that file, because every installed app would refuse the update.

To release version `X.Y.Z`: set `version = "X.Y.Z"` in `NIH Extractor/pyproject.toml` and `__version__` in `NIH Extractor/nih_grant_matcher/__init__.py`, run `uv lock` in `NIH Extractor/`, merge that to `main`, then tag the merged commit `vX.Y.Z` and push the tag.

Three rules keep installed apps able to update:

- A release that carries no `appcast.xml` must not become the newest release. Create such a release with `gh release create --latest=false`, or as a pre-release.
- To withdraw a bad release, mark it as a pre-release. The feed then falls back to the release before it. Users who already installed the bad release stay on it, because Sparkle does not downgrade, so publish a fixed version with a higher number. Version 0.1.1 has no feed, so do not fall back to it.
- Change the update key or the Developer ID certificate in separate releases, never both in one. An installed app accepts a release with a new key only when the disk image is signed with the same Developer ID certificate, and the workflow checks the feed against the new build's key only. A lost seed is replaced this way: create a new key, commit its public half, set the secret, and release.

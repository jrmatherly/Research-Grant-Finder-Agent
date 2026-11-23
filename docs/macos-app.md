# Build NIH Grant Matcher as a macOS app

`Grant Matcher.app` shows the dashboard in its own window. It starts the dashboard server on a free port on `127.0.0.1` and stops it when you quit.

## Download

Each release on the [releases page](https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases) carries `Grant-Matcher-<version>-arm64.dmg`, signed with a Developer ID certificate and notarized by Apple, and a `.sha256` file to check it against. It needs a Mac with Apple silicon and macOS 14 or later. Open the disk image and drag `Grant Matcher` to `Applications`.

The rest of this page is for building the app yourself with `NIH Extractor/macos/build.sh`.

## Before you begin

- A Mac with Apple silicon and macOS 14 or later. The build makes an `arm64` app only.
- The Xcode command line tools, or Xcode. `xcode-select -p` prints their folder when they are installed.
- [uv](https://docs.astral.sh/uv/). The build installs PyInstaller and pywebview from the `macos` dependency group in `pyproject.toml`. `uv sync` without `--group macos` does not install them.

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

The build takes a few minutes. It then starts the server from the built app and fails if the dashboard script does not run cleanly within 30 seconds. With `CODESIGN_IDENTITY` set, it also checks the app's signature and signs the disk image.

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

## Notarize

A Mac blocks an app that arrives from another computer unless Apple has notarized it. A build you run on the Mac that made it does not need this step.

The build notarizes the `.dmg` and staples the ticket to it when `CODESIGN_IDENTITY` is set together with one of these:

- `NOTARY_PROFILE`, the name of a keychain profile made with `xcrun notarytool store-credentials`.
- `APPLE_API_KEY_P8`, `APPLE_API_KEY_ID` and `APPLE_API_ISSUER_ID`, an App Store Connect API key. The release workflow uses these.

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" NOTARY_PROFILE=grant-matcher "NIH Extractor/macos/build.sh"
```

The notarization step is untested on a developer's Mac. The first release run is its first test.

Use a Developer ID Application certificate issued by the Developer ID G2 Sub-CA. The older Developer ID Certification Authority expires on 2027-02-01, and the certificates it issued expire with it. `security find-certificate -c "Developer ID Application" -p | openssl x509 -noout -issuer -enddate` shows the issuer and the end date of your certificate.

## Publish a release

`.github/workflows/macos-release.yml` runs on a `v*` tag. It builds, signs and notarizes the disk image on an Apple silicon runner, then attaches `Grant-Matcher-<version>-arm64.dmg` and its checksum to the tag's GitHub release. The same tag also publishes the Docker image.

The workflow stops before it builds when the tag does not equal `v` plus the `version` in `NIH Extractor/pyproject.toml`, when the tagged commit is not on `main`, or when a secret is missing. It never replaces an asset on an existing release.

The repository needs five Actions secrets:

| Secret | Contents |
| --- | --- |
| `MACOS_CERT_P12` | The Developer ID Application certificate and its private key, exported as a `.p12` file and base64-encoded |
| `MACOS_CERT_PASSWORD` | The password set when the `.p12` file was exported |
| `APPLE_API_KEY_ID` | The Key ID of an App Store Connect API key |
| `APPLE_API_ISSUER_ID` | The Issuer ID shown above the keys in App Store Connect |
| `APPLE_API_KEY_P8` | The text of the key's `AuthKey_<Key ID>.p8` file |

To release version `X.Y.Z`: set `version = "X.Y.Z"` in `NIH Extractor/pyproject.toml`, run `uv lock` there, merge that to `main`, then tag the merged commit `vX.Y.Z` and push the tag.

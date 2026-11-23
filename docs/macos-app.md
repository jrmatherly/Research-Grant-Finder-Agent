# Build NIH Grant Matcher as a macOS app

`NIH Extractor/macos/build.sh` builds `Grant Matcher.app`, which shows the dashboard in its own window, and a disk image that holds it. The app starts the dashboard server on a free port on `127.0.0.1` and stops it when you quit.

The app is for your own use on your own Mac. The root `LICENSE` covers this fork's changes only, and the original upstream work has no licence, so do not publish or hand out the `.dmg`.

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

## Notarize to use the app on another Mac

You need this step only to move the `.dmg` to another Mac you own. Gatekeeper on that Mac blocks an app that arrives from another computer and that Apple has not notarized.

1. Store your App Store Connect credentials in the keychain under a profile name, for example `grant-matcher`. See `xcrun notarytool store-credentials --help`.
2. Build with both variables set. The build sends the `.dmg` to Apple, waits for the result, and staples the ticket to the `.dmg`.

   ```bash
   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" NOTARY_PROFILE=grant-matcher "NIH Extractor/macos/build.sh"
   ```

   The notarization step is untested.

Use a Developer ID Application certificate issued by the Developer ID G2 Sub-CA. The older Developer ID Certification Authority expires on 2027-02-01, and the certificates it issued expire with it. `security find-certificate -c "Developer ID Application" -p | openssl x509 -noout -issuer -enddate` shows the issuer and the end date of your certificate.

#!/usr/bin/env bash
# Prints the update feed for one release: macos/make-appcast.sh <dmg> <version>. Reads the private seed from SPARKLE_ED_KEY.
set -euo pipefail

dmg=${1:?usage: make-appcast.sh <dmg> <version>}
version=${2:?usage: make-appcast.sh <dmg> <version>}
sign_update=${SIGN_UPDATE:-$(dirname "$0")/build/sparkle/bin/sign_update}
base=${APPCAST_DOWNLOAD_BASE:-https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/download/v$version}

[ -n "${SPARKLE_ED_KEY:-}" ] || { echo "SPARKLE_ED_KEY is not set, so the disk image cannot be signed." >&2; exit 1; }
[ -f "$dmg" ] || { echo "The disk image $dmg does not exist." >&2; exit 1; }
[ -x "$sign_update" ] || { echo "$sign_update is missing. macos/build.sh fetches it." >&2; exit 1; }

# The seed goes in on standard input, because an argument shows in the process list.
signature=$(printf '%s' "$SPARKLE_ED_KEY" | "$sign_update" --ed-key-file - -p "$dmg")
printf '%s' "$SPARKLE_ED_KEY" | "$sign_update" --verify --ed-key-file - "$dmg" "$signature" > /dev/null
length=$(($(wc -c < "$dmg")))

cat <<XML
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
XML

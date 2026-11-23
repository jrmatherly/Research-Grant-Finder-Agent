#!/usr/bin/env bash
# Checks a feed as an installed app would: macos/verify-appcast.sh <app> <dmg> <appcast>. Needs no secret.
set -euo pipefail

app=${1:?usage: verify-appcast.sh <app> <dmg> <appcast>}
dmg=${2:?usage: verify-appcast.sh <app> <dmg> <appcast>}
appcast=${3:?usage: verify-appcast.sh <app> <dmg> <appcast>}

xmllint --noout "$appcast" || { echo "Feed check failed: $appcast is not well-formed XML." >&2; exit 1; }
# sparkle:edSignature is in a namespace, so both attributes are matched by local name.
attribute() { xmllint --xpath "string(//*[local-name()='enclosure']/@*[local-name()='$1'])" "$appcast"; }
length=$(attribute length)
signature=$(attribute edSignature)
[ "$length" = "$(($(wc -c < "$dmg")))" ] || { echo "Length check failed: the feed says $length bytes, and $dmg has $(($(wc -c < "$dmg")))." >&2; exit 1; }
[ -n "$signature" ] || { echo "Signature check failed: the feed has no sparkle:edSignature." >&2; exit 1; }
public_key=$(plutil -extract SUPublicEDKey raw -o - "$app/Contents/Info.plist") || { echo "Key check failed: $app has no SUPublicEDKey." >&2; exit 1; }
swift "$(dirname "$0")/verify-signature.swift" "$public_key" "$signature" "$dmg" || { echo "Signature check failed: the public key in $app does not accept the feed's signature of $dmg. SPARKLE_ED_KEY does not match macos/sparkle-public-key.txt." >&2; exit 1; }
echo "Feed verified: $appcast"

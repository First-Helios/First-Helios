#!/usr/bin/env bash
# Install the pinned restic as /usr/local/bin/restic (ADR-0031 D1, Q1).
#   sudo bash infra/backup/install-restic.sh
# Ubuntu 22.04's packaged restic (0.12) predates compression and --stdin-from-command (0.17), so
# this pins a release by version and sha256. The sums are copied from the release's SHA256SUMS,
# whose signature was checked against the restic maintainers' key
# CF8F 18F2 8445 7597 3F79  D4E1 91A6 868B D3F7 A907 when the pin was set (2026-11-27).
# To move the pin: the new release's SHA256SUMS, its signature checked the same way, both lines.
set -euo pipefail
VERSION=0.19.1
case "$(uname -m)" in
  aarch64 | arm64) ARCH=arm64 SHA256=a5f64aaab53d51e311fa3829124c5b703f2d14cf187d8640b6be3b2b49376465 ;;
  x86_64) ARCH=amd64 SHA256=f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c ;;
  *)
    echo "error: no pinned restic for $(uname -m)" >&2
    exit 1
    ;;
esac
if [ "$(/usr/local/bin/restic version 2>/dev/null | cut -d' ' -f2)" = "$VERSION" ]; then
  echo "restic $VERSION is already installed"
  exit 0
fi
[ "$(id -u)" = 0 ] || {
  echo "error: run with sudo (installs to /usr/local/bin)" >&2
  exit 1
}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FILE=restic_${VERSION}_linux_${ARCH}.bz2
curl -fsSL --retry 3 -o "$TMP/$FILE" "https://github.com/restic/restic/releases/download/v$VERSION/$FILE"
echo "$SHA256  $TMP/$FILE" | sha256sum -c --quiet -
bunzip2 "$TMP/$FILE"
install -m 0755 "$TMP/${FILE%.bz2}" /usr/local/bin/restic
/usr/local/bin/restic version

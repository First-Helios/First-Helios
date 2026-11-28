#!/usr/bin/env bash
# A freshly flashed Orange Pi OS (Ubuntu 22.04) to a host that can restore and serve Helios
# (ADR-0031 D2, drill B; a real loss of the Pi too). The runbook is infra/backup/README.md.
#   curl -fsSLO https://raw.githubusercontent.com/First-Helios/First-Helios/<commit>/infra/backup/bootstrap.sh
#   sudo bash bootstrap.sh <commit>
# <commit> is the night's manifest "commit". In order:
#   1. Docker Engine and the Compose plugin, from Docker's apt repository;
#   2. cloudflared, from Cloudflare's apt repository (the tunnel token is a later, manual step);
#   3. the code: GitHub's tarball of <commit> into ~/First-Helios, with DEPLOYED_COMMIT, and
#      an empty .env (mode 0600) when there is none;
#   4. the pinned restic (install-restic.sh, from that tarball);
#   5. ~/.config/helios-ops/ (mode 0700) for r2.env and restic-password;
#   6. helios-frontend.service (dev_server.py on 127.0.0.1:8080, as on the Pi since 2026-10-26),
#      installed and enabled but not started: the frontend files come from the laptop later.
# The user is the one running sudo (orangepi on a stock image), added to the docker group.
# Nothing here starts a database, restores data or touches the tunnel.
set -euo pipefail
COMMIT=${1:?usage: sudo bash bootstrap.sh <commit>}
[[ "$COMMIT" =~ ^[0-9a-f]{7,40}$ ]] || {
  echo "error: not a commit: '$COMMIT'" >&2
  exit 1
}
[ "$(id -u)" = 0 ] || {
  echo "error: run with sudo" >&2
  exit 1
}
OWNER=${SUDO_USER:-orangepi}
HOME_DIR=$(getent passwd "$OWNER" | cut -d: -f6)
DEPLOY=$HOME_DIR/First-Helios
REPO=First-Helios/First-Helios
log() { echo "$(date -u +%FT%TZ) $*"; }
start=$SECONDS
export DEBIAN_FRONTEND=noninteractive

log "1. Docker Engine (download.docker.com)"
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg bzip2 rsync
install -m 0755 -d /etc/apt/keyrings
curl -fsSL "https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg" -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091 # the host's os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  >/etc/apt/sources.list.d/docker.list

log "2. cloudflared (pkg.cloudflare.com)"
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  >/etc/apt/sources.list.d/cloudflared.list

apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin cloudflared
systemctl enable --now docker
usermod -aG docker "$OWNER"

log "3. code at $COMMIT -> $DEPLOY"
install -d -o "$OWNER" -g "$OWNER" "$DEPLOY"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$COMMIT" |
  tar -xz --strip-components=1 -C "$DEPLOY"
echo "$COMMIT" >"$DEPLOY/DEPLOYED_COMMIT"
if [ ! -e "$DEPLOY/.env" ]; then
  # Compose's defaults need nothing here until Postgres moves off helios/helios (ADR-0031 Q6b);
  # then POSTGRES_PASSWORD and HELIOS_COMPOSE_DATABASE_URL come from the password manager.
  install -m 0600 /dev/null "$DEPLOY/.env"
fi
chown -R "$OWNER:$OWNER" "$DEPLOY"

log "4. restic"
bash "$DEPLOY/infra/backup/install-restic.sh"

log "5. ~/.config/helios-ops"
install -d -m 0700 -o "$OWNER" -g "$OWNER" "$HOME_DIR/.config" "$HOME_DIR/.config/helios-ops"

log "6. helios-frontend.service (enabled, not started)"
cat >/etc/systemd/system/helios-frontend.service <<UNIT
[Unit]
Description=Helios frontend (dev_server.py on 127.0.0.1:8080; Cloudflare Tunnel serves it as firsthelios.com)
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=$OWNER
WorkingDirectory=$HOME_DIR/First-Helios_Frontend
ExecStart=/usr/bin/python3 dev_server.py --api http://127.0.0.1:8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable helios-frontend.service

log "bootstrap done in $((SECONDS - start)) s: docker $(docker --version | cut -d' ' -f3 | tr -d ,), $(cloudflared --version | head -n 1)"
log "next: log out and back in (docker group), then infra/backup/README.md, drill B step 3"

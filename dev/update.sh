#!/bin/bash
# Auto-update script — pulls latest from GitHub and restarts if changed.
# Run by helios-update.timer every 5 minutes.
set -e
REPO=~/First-Helios
LOG=/var/log/helios-update.log

cd $REPO

git fetch origin main >> $LOG 2>&1 || { echo "$(date) fetch failed" >> $LOG; exit 1; }

LOCAL=$(git rev-parse HEAD 2>/dev/null || echo 'none')
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "$(date) Updating $LOCAL -> $REMOTE" >> $LOG
git reset --hard origin/main >> $LOG 2>&1

# Install any new/changed deps
.venv/bin/pip install -r requirements.txt -q >> $LOG 2>&1 || true

# Restart server (service runs as root via systemd, no sudo needed)
systemctl restart helios >> $LOG 2>&1
echo "$(date) Restart done" >> $LOG

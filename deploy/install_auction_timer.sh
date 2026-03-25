#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="/home/ubuntu/auction-bot/deploy"
DST_DIR="/etc/systemd/system"

sudo cp -f "${SRC_DIR}/auction-daily.service" "${DST_DIR}/auction-daily.service"
sudo cp -f "${SRC_DIR}/auction-daily.timer" "${DST_DIR}/auction-daily.timer"

sudo systemctl daemon-reload
sudo systemctl enable --now auction-daily.timer
sudo systemctl status auction-daily.timer --no-pager

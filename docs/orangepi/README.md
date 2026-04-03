# OrangePi 5 Plus — Operations Docs

This folder contains operational documentation for the OrangePi 5 Plus production host running First-Helios.

## Contents

| File | Description |
|------|-------------|
| [server_reboot.md](server_reboot.md) | Step-by-step reboot and recovery sequence |
| [postgres_tuning.md](postgres_tuning.md) | PostgreSQL connection limits and performance config |

## Quick Reference

| Item | Value |
|------|-------|
| Host | `192.168.0.104` |
| SSH | `ssh orangepi@192.168.0.104` (password: see `.env` notes) |
| Web | `http://192.168.0.104` |
| SoC | Rockchip RK3588, ARM64 |
| RAM | 32 GB |
| OS | Ubuntu Jammy (22.04) |
| PostgreSQL | 14, port 5432 |
| Gunicorn port | 8765 (proxied by nginx on 80) |

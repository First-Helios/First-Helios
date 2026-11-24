#!/usr/bin/env bash
# The laptop GPU's llama-server, for a master on the Pi (ADR-0030 Q3) or on the laptop.
#   DATA=<laptop deploy dir> bash infra/pipeline-host/laptop-llama.sh up [bind address]
#   bash infra/pipeline-host/laptop-llama.sh down
# `up` checks the model file's sha256, starts the container (P8-23's CUDA image and flags) on
# <bind address>:8083 (default 127.0.0.1; the laptop's LAN address only while a Pi run uses it)
# and waits for /health. The server has no API key (see the README). Pause it by GPU heat with:
#   python3 -m apps.menu_pipeline.batch_loop --host laptop --phase gpu-watch --data-dir "$DATA"
set -euo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
# shellcheck source=infra/pipeline-host/lib.sh
. infra/pipeline-host/lib.sh
NAME=helios-llama-gpu
MODEL_DIR="$(realpath "$DATA")/var/models/Qwen3-4B-Instruct-2507-Q4_0"
MODEL_SHA=e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2
IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6
case "${1:-}" in
up)
  BIND=${2:-127.0.0.1}
  echo "$MODEL_SHA  $MODEL_DIR/Qwen3-4B-Instruct-2507-Q4_0.gguf" | sha256sum -c --quiet
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \
    -p "$BIND:8083:8080" -v "$MODEL_DIR:/models:ro" "$IMAGE" \
    --model /models/Qwen3-4B-Instruct-2507-Q4_0.gguf --host 0.0.0.0 --port 8080 \
    --n-gpu-layers 99 --parallel 2 --ctx-size 12288 --flash-attn off --cache-ram 0 >/dev/null
  for _ in $(seq 1 90); do
    curl -sf "http://$BIND:8083/health" >/dev/null && {
      log "llama-server up on $BIND:8083"
      exit 0
    }
    sleep 2
  done
  die "llama-server did not answer /health on $BIND:8083"
  ;;
down)
  docker rm -f "$NAME" >/dev/null
  log "llama-server removed"
  ;;
*) die "usage: laptop-llama.sh <up [bind address]|down>" ;;
esac

# llama-server image check on the Pi (ADR-0013 §3, Amendment 6)

ADR-0013 §3 runs `llama-server` from the upstream llama.cpp image only if its arm64
build matches the spike's measured Pi speed. Session P5-3 shipped upstream
`server-b11176` (pinned by digest in `infra/docker-compose.yml`); the spike's binary
is a native build of `84e76d8` (= `b11173`) in `~/menu-model-spike/llama.cpp` on
the Pi. Agents don't access the Pi, so the owner runs this check before the first Pi
extraction run.

**Pass:** the container's median prompt tokens/s and median generation tokens/s are
each ≥ 95% of the spike binary's, with the same flags, the same four A76 cores and
the same request. **Fail:** a follow-up PR adds `infra/llama/Dockerfile` (a pinned
source build of `84e76d8`) and repeats this check with it. Whether both builds give
the same greedy output is recorded, not gated.

## Laptop smoke test (P5-3, amd64)

Not the check: a laptop has no A76 cores. With the spike's GGUF under `var/models/`:
`llama-model-check` passed and `llama-server` reported healthy within seconds; no
host port was published; a container on the Compose network reached
`http://llama-server:8080/health`; `/props` reported 2 slots of 4,096 tokens and
`/models/Qwen3-4B-Instruct-2507-Q4_0.gguf`; a 12-token greedy completion decoded at
13.8 tokens/s; memory 2.5 GiB of the 8 GiB limit. With a wrong file in its place,
`llama-model-check` exited 1 (`does not match config/models.yaml`) and
`llama-server` was created but never started.

## Steps (owner, on the Pi)

At the merged commit's deploy directory. Cool the SoC below 55 °C before each run,
as the spike did (`cat /sys/class/thermal/thermal_zone0/temp`).

```bash
# 1. The model file: the spike's copy (the manifest pins the same bytes).
mkdir -p var/models/Qwen3-4B-Instruct-2507-Q4_0 var/llama-check
cp ~/menu-model-spike/gguf/Qwen3-4B-Instruct-2507-Q4_0.gguf var/models/Qwen3-4B-Instruct-2507-Q4_0/
chmod 644 var/models/Qwen3-4B-Instruct-2507-Q4_0/*.gguf

# 2. One fixed request: a ~1.5k-character menu-like prompt, 256 generated tokens,
#    greedy, no prompt cache (so every run reads the prompt again).
python3 - > var/llama-check/body.json <<'EOF'
import json
lines = [f"Item {i} with roasted peppers and house sauce ${5 + i % 20}.{i % 4 * 25:02d}" for i in range(28)]
print(json.dumps({"prompt": "List the menu items as JSON.\n" + "\n".join(lines),
                  "n_predict": 256, "ignore_eos": True, "temperature": 0, "cache_prompt": False}))
EOF

# 3. The spike binary, on the A76 cores, with the service's flags.
taskset -c 4-7 ~/menu-model-spike/llama.cpp/build/bin/llama-server \
  -m var/models/Qwen3-4B-Instruct-2507-Q4_0/Qwen3-4B-Instruct-2507-Q4_0.gguf \
  --host 127.0.0.1 --port 8080 -t 4 -c 8192 -np 2 -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 &
until curl -sf 127.0.0.1:8080/health >/dev/null; do sleep 2; done
for i in 1 2 3; do curl -s -d @var/llama-check/body.json 127.0.0.1:8080/completion > var/llama-check/spike-$i.json; done
kill %1

# 4. The service (Pi override: CPUs 4-7), same request from inside the container.
COMPOSE="docker compose -f infra/docker-compose.yml -f infra/docker-compose.pi.yml --env-file .env --profile menu"
$COMPOSE up -d --wait llama-server
for i in 1 2 3; do
  $COMPOSE exec -T llama-server curl -s -d @- localhost:8080/completion \
    < var/llama-check/body.json > var/llama-check/image-$i.json
done
docker stats --no-stream helios-llama-server-1
$COMPOSE stop llama-server

# 5. Medians, the ratio and output identity.
python3 - <<'EOF'
import json, statistics
def load(tag):
    return [json.load(open(f"var/llama-check/{tag}-{i}.json")) for i in (1, 2, 3)]
spike, image = load("spike"), load("image")
for key in ("prompt_per_second", "predicted_per_second"):
    s = statistics.median(r["timings"][key] for r in spike)
    m = statistics.median(r["timings"][key] for r in image)
    print(f"{key}: spike {s:.2f}  image {m:.2f}  ratio {m / s:.3f}  pass {m / s >= 0.95}")
print("prompt tokens:", spike[0]["timings"]["prompt_n"])
print("same greedy output:", {r["content"] for r in spike} == {r["content"] for r in image})
EOF
```

## Result

| Pi check | Result |
|---|---|
| Prompt tokens/s, spike binary / image (median of 3) | *pending (owner)* |
| Generation tokens/s, spike binary / image (median of 3) | *pending* |
| Ratios (pass ≥ 0.95 each) | *pending* |
| Same greedy output | *pending* |
| Container memory after the runs | *pending* |

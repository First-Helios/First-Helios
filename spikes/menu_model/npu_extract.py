"""Step E on the RK3588 NPU: the same extractor through Rockchip's RKLLM runtime.

    MENU_SPIKE_DATA=... python -m spikes.menu_model.npu_extract --lib LIB --model M.rkllm --tag TAG [PAGE ...]

Same system prompt, chunks, output shape and result files as ``extract run``,
so ``extract score --tag TAG`` scores it unchanged. Differences, reported with
the results: RKLLM (v1.2.3) has no grammar / JSON-schema constraint, so the
assistant turn is pre-filled with ``{"sections": [`` and the rest is parsed
leniently (:func:`spikes.menu_model.extract.parse_output`); decoding is greedy
(``top_k=1``) like ``temperature=0`` on llama.cpp.

The ctypes structs mirror ``rkllm.h`` of runtime release v1.2.3 exactly; another
runtime version needs its own header check.
"""

from __future__ import annotations

import ctypes as C
import json
import sys
import time
from typing import Any

from spikes.menu_model.eval_validator import load_gold
from spikes.menu_model.extract import DATA, MAX_TOKENS, SYSTEM, chunks, parse_output

PREFILL = '{"sections": [{"section": "'
# no grammar on the NPU: the shape the llama.cpp schema enforces, shown as one example
FORMAT = (
    '{"sections": [{"section": "Tacos", "rows": [["b0012", "Carne Asada Taco", "3.50", ""], '
    '["b0014", "Al Pastor Taco", "3.25", ""]]}, {"section": "Drinks", "rows": '
    '[["b0020", "Horchata", "2.50", "Small"], ["b0020", "Horchata", "3.50", "Large"]]}]} '
    "and so on: list every item on the page, not just the first."
)
RUN_NORMAL, RUN_WAITING, RUN_FINISH, RUN_ERROR = 0, 1, 2, 3


class ExtendParam(C.Structure):
    _fields_ = [
        ("base_domain_id", C.c_int32),
        ("embed_flash", C.c_int8),
        ("enabled_cpus_num", C.c_int8),
        ("enabled_cpus_mask", C.c_uint32),
        ("n_batch", C.c_uint8),
        ("use_cross_attn", C.c_int8),
        ("reserved", C.c_uint8 * 104),
    ]


class Param(C.Structure):
    _fields_ = [
        ("model_path", C.c_char_p),
        ("max_context_len", C.c_int32),
        ("max_new_tokens", C.c_int32),
        ("top_k", C.c_int32),
        ("n_keep", C.c_int32),
        ("top_p", C.c_float),
        ("temperature", C.c_float),
        ("repeat_penalty", C.c_float),
        ("frequency_penalty", C.c_float),
        ("presence_penalty", C.c_float),
        ("mirostat", C.c_int32),
        ("mirostat_tau", C.c_float),
        ("mirostat_eta", C.c_float),
        ("skip_special_token", C.c_bool),
        ("is_async", C.c_bool),
        ("img_start", C.c_char_p),
        ("img_end", C.c_char_p),
        ("img_content", C.c_char_p),
        ("extend_param", ExtendParam),
    ]


class MultiModalInput(C.Structure):
    _fields_ = [
        ("prompt", C.c_char_p),
        ("image_embed", C.POINTER(C.c_float)),
        ("n_image_tokens", C.c_size_t),
        ("n_image", C.c_size_t),
        ("image_width", C.c_size_t),
        ("image_height", C.c_size_t),
    ]


class InputUnion(C.Union):
    _fields_ = [("prompt_input", C.c_char_p), ("multimodal_input", MultiModalInput)]


class Input(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("role", C.c_char_p),
        ("enable_thinking", C.c_bool),
        ("input_type", C.c_int),
        ("u", InputUnion),
    ]


class InferParam(C.Structure):
    _fields_ = [
        ("mode", C.c_int),
        ("lora_params", C.c_void_p),
        ("prompt_cache_params", C.c_void_p),
        ("keep_history", C.c_int),
    ]


class HiddenOrLogits(C.Structure):
    _fields_ = [("data", C.POINTER(C.c_float)), ("size", C.c_int), ("num_tokens", C.c_int)]


class PerfStat(C.Structure):
    _fields_ = [
        ("prefill_time_ms", C.c_float),
        ("prefill_tokens", C.c_int),
        ("generate_time_ms", C.c_float),
        ("generate_tokens", C.c_int),
        ("memory_usage_mb", C.c_float),
    ]


class Result(C.Structure):
    _fields_ = [
        ("text", C.c_char_p),
        ("token_id", C.c_int32),
        ("last_hidden_layer", HiddenOrLogits),
        ("logits", HiddenOrLogits),
        ("perf", PerfStat),
    ]


CALLBACK = C.CFUNCTYPE(C.c_int, C.POINTER(Result), C.c_void_p, C.c_int)


class Rkllm:
    def __init__(  # noqa: PLR0913 - one keyword per runtime knob
        self,
        lib: str,
        model: str,
        *,
        max_context: int,
        cpus_mask: int,
        embed_flash: int = 0,
        domain: int = 0,
    ) -> None:
        self.lib = C.CDLL(lib)
        self.lib.rkllm_createDefaultParam.restype = Param
        self.lib.rkllm_init.argtypes = [C.POINTER(C.c_void_p), C.POINTER(Param), CALLBACK]
        self.lib.rkllm_run.argtypes = [
            C.c_void_p,
            C.POINTER(Input),
            C.POINTER(InferParam),
            C.c_void_p,
        ]
        self.lib.rkllm_set_chat_template.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_char_p]
        self.lib.rkllm_clear_kv_cache.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_void_p]
        self._parts: list[bytes] = []
        self._perf: dict[str, float] = {}
        self._error = False
        self._cb = CALLBACK(self._on_result)  # keep a reference for the library's lifetime

        p = self.lib.rkllm_createDefaultParam()
        p.model_path = model.encode()
        p.max_context_len = max_context
        p.max_new_tokens = MAX_TOKENS
        p.top_k = 1
        p.top_p = 1.0
        p.temperature = 1.0
        p.repeat_penalty = 1.0
        p.frequency_penalty = 0.0
        p.presence_penalty = 0.0
        p.skip_special_token = True
        p.is_async = False
        p.extend_param.base_domain_id = domain  # a second IOMMU domain for large models
        p.extend_param.embed_flash = (
            embed_flash  # embedding table read from storage, not NPU memory
        )
        p.extend_param.enabled_cpus_num = bin(cpus_mask).count("1")
        p.extend_param.enabled_cpus_mask = cpus_mask
        p.extend_param.n_batch = 1
        self.handle = C.c_void_p()
        rc = self.lib.rkllm_init(C.byref(self.handle), C.byref(p), self._cb)
        if rc != 0:
            raise RuntimeError(f"rkllm_init failed: {rc}")
        # Qwen ChatML with the system prompt baked in; the assistant turn starts with PREFILL.
        system = f"<|im_start|>system\n{SYSTEM}\nOutput only JSON like: {FORMAT}<|im_end|>\n"
        rc = self.lib.rkllm_set_chat_template(
            self.handle,
            system.encode(),
            b"<|im_start|>user\n",
            f"<|im_end|>\n<|im_start|>assistant\n{PREFILL}".encode(),
        )
        if rc != 0:
            raise RuntimeError(f"rkllm_set_chat_template failed: {rc}")

    def _on_result(self, result: Any, _userdata: object, state: int) -> int:
        if state == RUN_NORMAL and result.contents.text:
            self._parts.append(result.contents.text)
        elif state == RUN_FINISH:
            perf = result.contents.perf
            self._perf = {
                "prompt_n": perf.prefill_tokens,
                "prompt_ms": perf.prefill_time_ms,
                "predicted_n": perf.generate_tokens,
                "predicted_ms": perf.generate_time_ms,
                "memory_usage_mb": perf.memory_usage_mb,
            }
        elif state == RUN_ERROR:
            self._error = True
        return 0

    def generate(self, user: str) -> dict[str, Any]:
        self._parts, self._perf, self._error = [], {}, False
        inp = Input(role=b"user", enable_thinking=False, input_type=0)
        inp.prompt_input = user.encode()
        infer = InferParam(mode=0, lora_params=None, prompt_cache_params=None, keep_history=0)
        t0 = time.perf_counter()
        rc = self.lib.rkllm_run(self.handle, C.byref(inp), C.byref(infer), None)
        wall = time.perf_counter() - t0
        self.lib.rkllm_clear_kv_cache(self.handle, 1, None, None)
        content = PREFILL + b"".join(self._parts).decode("utf-8", errors="replace")
        n = int(self._perf.get("predicted_n", 0))
        return {
            "wall_s": round(wall, 2),
            "finish": "error" if rc or self._error else "length" if n >= MAX_TOKENS else "stop",
            "timings": self._perf,
            "raw": content,
            "out": parse_output(content),
        }


def main() -> None:
    args = sys.argv[1:]
    opt = {
        k: args[args.index(k) + 1]
        for k in ("--lib", "--model", "--tag", "--ctx", "--cpus", "--embed-flash", "--domain")
        if k in args
    }
    skip = set(opt.values()) | set(opt)
    pages = [a for a in args if a not in skip] or sorted(load_gold())
    llm = Rkllm(
        opt["--lib"],
        opt["--model"],
        max_context=int(opt.get("--ctx", "8192")),
        cpus_mask=int(opt.get("--cpus", "0xF0"), 16),  # the four A76 cores (CPU4-7)
        embed_flash=int(opt.get("--embed-flash", "0")),
        domain=int(opt.get("--domain", "0")),
    )
    out_dir = DATA / "extract" / opt["--tag"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for pid in pages:
        path = out_dir / f"{pid}.json"
        if path.exists():
            continue
        t0 = time.perf_counter()
        results = [llm.generate(c) for c in chunks(pid)]
        rec = {"page_id": pid, "wall_s": round(time.perf_counter() - t0, 2), "chunks": results}
        path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        gen = sum(int(ch["timings"].get("predicted_n", 0)) for ch in results)
        rows = sum(
            len(sec.get("rows", [])) for ch in results for sec in ch["out"].get("sections", [])
        )
        print(
            f"{pid} chunks={len(results)} rows={rows} gen_tokens={gen} wall={rec['wall_s']}s",
            flush=True,
        )


if __name__ == "__main__":
    main()

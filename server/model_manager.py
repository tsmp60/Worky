"""
Owns the text model instances (Chat and Coder pages each get their own
slot). Only one model lives in memory per page at a time: loading a new
one for a page automatically frees the previous one first.

Two model formats are supported, auto-detected from the path:

  - A .gguf file -> loaded with llama-cpp-python, which runs inference
    through llama.cpp's compiled C++ core. Fast and light on RAM;
    the recommended format for an 8GB/no-GPU machine.

  - A folder in standard Hugging Face format (config.json, tokenizer
    files, and .safetensors weights) -> loaded with transformers,
    running full-precision CPU inference. This works but is
    meaningfully slower and heavier on RAM than a GGUF model of the
    same size, since there is no CPU-specific quantization involved.
    A single loose .safetensors file with no config/tokenizer next to
    it cannot be loaded this way; point at the folder that contains it.
"""

import gc
import os
import re
import threading
import time
import json
from pathlib import Path

from server import config_store

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer, StoppingCriteria, StoppingCriteriaList
except ImportError:
    torch = None
    StoppingCriteria = object
    StoppingCriteriaList = None

try:
    import accelerate  # noqa: F401
    _HAS_ACCELERATE = True
except ImportError:
    _HAS_ACCELERATE = False

THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)

_lock = threading.Lock()
_engines: dict[str, object] = {}
_status: dict[str, dict] = {
    "chat": {"loaded": False, "model_path": "", "error": None},
    "coder": {"loaded": False, "model_path": "", "error": None},
}


def _detect_format(model_path: str) -> str:
    if model_path.lower().endswith(".gguf"):
        return "gguf"
    if os.path.isdir(model_path):
        return "hf"
    if model_path.lower().endswith(".safetensors"):
        return "loose_safetensors"
    return "unknown"


def _render_custom_template(template: str, messages: list[dict]) -> str:
    """Render the common Ollama/Go chat-template subset used by model templates."""
    if not template.strip():
        return ""
    # If a complete Ollama Modelfile was pasted, extract its TEMPLATE body.
    modelfile_match = re.search(r'(?s)TEMPLATE\s+"""(.*?)"""', template)
    if modelfile_match:
        template = modelfile_match.group(1)
    # Expand {{ range .Messages }} ... {{ end }} over each role/content pair.
    range_pattern = re.compile(r"{{\s*range\s+\.Messages\s*}}(.*?){{\s*end\s*}}", re.DOTALL)
    match = range_pattern.search(template)
    rendered = template
    if match:
        body = match.group(1)
        expanded = []
        for message in messages:
            item = body.replace("{{ .Role }}", str(message.get("role", "user")))
            item = item.replace("{{.Role}}", str(message.get("role", "user")))
            item = item.replace("{{ .Content }}", str(message.get("content", "")))
            item = item.replace("{{.Content}}", str(message.get("content", "")))
            expanded.append(item)
        rendered = rendered[:match.start()] + "".join(expanded) + rendered[match.end():]
    # Handle the common simple-message iteration form if template used .Messages directly.
    rendered = rendered.replace("{{ .System }}", "")
    rendered = rendered.replace("{{ .Prompt }}", "")
    # Strip Ollama Modelfile directives if pasted as a complete snippet.
    rendered = re.sub(r"(?m)^\s*(TEMPLATE|PARAMETER)\s+.*$", "", rendered)
    rendered = rendered.replace('"""', "")
    return rendered.strip()


class HFTextEngine:
    """Wraps a Hugging Face transformers text model behind the same
    create_chat_completion(...) shape llama-cpp-python exposes, so the
    rest of the app does not need to care which backend loaded it.

    RAM handling: if `accelerate` is installed and a RAM cap is set,
    the model is loaded with device_map="auto" and a max_memory limit,
    which makes accelerate keep only the layers that fit in that limit
    resident in RAM and stream the rest in from a disk offload folder
    as they're needed during generation. This is the real equivalent
    of "load only the chunks that are needed" for this format; without
    accelerate it falls back to loading the whole model into RAM at
    once, which only works if the model comfortably fits."""

    def __init__(self, model_path: str, n_threads: int, max_ram_gb: float = 0):
        torch.set_num_threads(max(1, n_threads))
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        offload_dir = Path(__file__).resolve().parent.parent / "data" / "offload"
        offload_dir.mkdir(parents=True, exist_ok=True)

        load_kwargs = dict(dtype=torch.float32, low_cpu_mem_usage=True)
        if max_ram_gb and _HAS_ACCELERATE:
            load_kwargs["device_map"] = "auto"
            load_kwargs["max_memory"] = {"cpu": f"{max_ram_gb}GiB"}
            load_kwargs["offload_folder"] = str(offload_dir)
            load_kwargs["offload_state_dict"] = True

        self.model = AutoModelForCausalLM.from_pretrained(model_path, **load_kwargs)
        self.model.eval()

    def _build_prompt(self, messages: list[dict], custom_template: str = "") -> str:
        if custom_template.strip():
            return _render_custom_template(custom_template, messages)
        if getattr(self.tokenizer, "chat_template", None):
            return self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        # Fallback for tokenizers with no chat template of their own.
        parts = [f"{m['role']}: {m['content']}" for m in messages]
        parts.append("assistant:")
        return "\n".join(parts)

    def create_chat_completion(self, messages, max_tokens=512, temperature=0.7, stream=True, custom_template="", stop=None):
        prompt = self._build_prompt(messages, custom_template)
        inputs = self.tokenizer(prompt, return_tensors="pt")
        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        stop_token_sequences = []
        for stop_text in (stop or []):
            try:
                ids = self.tokenizer.encode(stop_text, add_special_tokens=False)
                if ids:
                    stop_token_sequences.append(ids)
            except Exception:
                pass

        class StopOnConfiguredTokens(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                for ids in stop_token_sequences:
                    if input_ids.shape[-1] >= len(ids) and input_ids[0, -len(ids):].tolist() == ids:
                        return True
                return False

        stopping = StoppingCriteriaList([StopOnConfiguredTokens()]) if stop_token_sequences and StoppingCriteriaList else None
        gen_kwargs = dict(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=temperature > 0,
            temperature=max(temperature, 0.01),
            streamer=streamer,
            pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
        )
        if stopping is not None:
            gen_kwargs["stopping_criteria"] = stopping
        # Exceptions raised inside a generation thread otherwise leave the UI
        # waiting forever on the streamer. End the stream and surface the error.
        generation_error = []
        def _generate():
            try:
                with torch.inference_mode():
                    self.model.generate(**gen_kwargs)
            except Exception as exc:
                generation_error.append(exc)
                try:
                    streamer.end()
                except Exception:
                    pass
        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

        def _stream():
            for piece in streamer:
                if piece:
                    yield {"choices": [{"delta": {"content": piece}}]}
            thread.join(timeout=1)
            if generation_error:
                raise RuntimeError(f"Transformers text generation failed: {generation_error[0]}")
        return _stream()


def get_status(page: str) -> dict:
    return dict(_status.get(page, {"loaded": False, "model_path": "", "error": None}))


def unload(page: str) -> None:
    with _lock:
        engine = _engines.pop(page, None)
        _status[page] = {"loaded": False, "model_path": "", "error": None}
        del engine
        gc.collect()


def load(page: str, model_path: str) -> dict:
    # Older Worky versions accepted a selected .safetensors file. Preserve that
    # workflow: when it is inside a standard Hugging Face model directory, load
    # the directory so Transformers can find config/tokenizer/shard metadata.
    model_path = str(Path(model_path).expanduser())
    if model_path.lower().endswith(".safetensors") and Path(model_path).is_file():
        parent = Path(model_path).parent
        if (parent / "config.json").is_file():
            model_path = str(parent.resolve())
    fmt = _detect_format(model_path)

    if fmt == "loose_safetensors":
        _status[page] = {
            "loaded": False, "model_path": "", "error": None,
            "note": "This .safetensors file has no config.json in its parent folder. "
                    "For a text model, select a Hugging Face model folder containing "
                    "config.json and tokenizer files." 
        }
        return get_status(page)

    if fmt == "gguf" and Llama is None:
        _status[page] = {"loaded": False, "model_path": "", "error": "llama-cpp-python is not installed"}
        return get_status(page)

    if fmt == "hf" and torch is None:
        _status[page] = {"loaded": False, "model_path": "", "error": "transformers/torch are not installed"}
        return get_status(page)

    if fmt == "unknown":
        _status[page] = {"loaded": False, "model_path": "", "error": "Unrecognized model path"}
        return get_status(page)

    with _lock:
        # Free whatever was previously loaded on this page first.
        old = _engines.pop(page, None)
        del old
        gc.collect()

        cfg = config_store.load()
        try:
            t0 = time.time()
            if fmt == "gguf":
                # use_mmap means the OS maps the weight file into address
                # space and pages in only the parts actually touched during
                # inference, rather than reading the whole file upfront; it
                # also lets the OS reclaim those clean pages under memory
                # pressure instead of them being pinned in RAM. use_mlock
                # stays off so this reclaiming is allowed to happen.
                engine = Llama(
                    model_path=model_path,
                    n_ctx=cfg.get("n_ctx", 4096),
                    n_threads=cfg.get("n_threads", 4),
                    n_batch=128,
                    use_mmap=True,
                    use_mlock=False,
                    verbose=False,
                )
            else:  # fmt == "hf"
                engine = HFTextEngine(model_path, cfg.get("n_threads", 4), cfg.get("max_ram_gb", 0))

            _engines[page] = engine
            _status[page] = {
                "loaded": True,
                "model_path": model_path,
                "format": fmt,
                "error": None,
                "load_seconds": round(time.time() - t0, 1),
            }
            config_store.set_model_for_page(page, model_path)
        except Exception as e:
            _status[page] = {"loaded": False, "model_path": "", "error": str(e)}

    return get_status(page)


def is_loaded(page: str) -> bool:
    return page in _engines


def chat_complete(page: str, messages: list[dict], max_tokens: int = 1024,
                   temperature: float = 0.7):
    """
    Streams (reasoning_delta, content_delta) pairs from the model on the
    given page. reasoning_delta is populated only while the model is
    inside a <think>...</think> block (used by reasoning-tuned models);
    everything else comes back as content_delta.

    Tag boundaries are held back across chunks: if a chunk ends with
    text that could be the start of "<think>" or "</think>", that
    trailing part is withheld until the next chunk resolves it, so a
    tag split across two network chunks is never leaked as visible text.
    """
    engine = _engines.get(page)
    if engine is None:
        raise RuntimeError(f"No model loaded on the {page} page")

    cfg = config_store.load()
    custom_template = cfg.get("chat_template", "")
    stop_sequences = [line for line in cfg.get("stop_sequences", "<|im_end|>").splitlines() if line]
    if not stop_sequences:
        stop_sequences = ["<|im_end|>"]
    if isinstance(engine, HFTextEngine):
        stream = engine.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            stream=True, custom_template=custom_template, stop=stop_sequences,
        )
    elif custom_template.strip():
        prompt = _render_custom_template(custom_template, messages)
        stream = engine.create_completion(
            prompt=prompt, max_tokens=max_tokens, temperature=temperature,
            stream=True, stop=stop_sequences,
        )
    else:
        stream = engine.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            stream=True, stop=stop_sequences,
        )

    # Stop sequences are also filtered client-side for Transformers, whose
    # streamer API does not consistently support llama.cpp-style stop strings.
    in_think = False
    buffer = ""
    stopped = False
    pending_text = ""

    def _longest_partial_match(text: str, tag: str) -> int:
        """Length of the longest suffix of `text` that is also a
        prefix of `tag` (i.e. could still turn into `tag` with more
        incoming text). Returns 0 if there's no such overlap."""
        max_k = min(len(text), len(tag) - 1)
        for k in range(max_k, 0, -1):
            if text[-k:] == tag[:k]:
                return k
        return 0

    for chunk in stream:
        delta = chunk["choices"][0]["delta"]
        piece = delta.get("content")
        if not piece:
            continue
        pending_text += piece
        hit_positions = [(pending_text.find(stop), stop) for stop in stop_sequences if pending_text.find(stop) >= 0]
        if hit_positions:
            pos, _stop = min(hit_positions, key=lambda item: item[0])
            piece = pending_text[:pos]
            pending_text = ""
            stopped = True
        else:
            hold_len = max((len(stop) - 1 for stop in stop_sequences), default=0)
            if hold_len and len(pending_text) <= hold_len:
                continue
            safe_len = max(0, len(pending_text) - hold_len)
            piece = pending_text[:safe_len] if hold_len else pending_text
            pending_text = pending_text[safe_len:] if hold_len else ""
        buffer += piece

        while True:
            tag = "</think>" if in_think else "<think>"
            idx = buffer.find(tag)
            if idx != -1:
                before = buffer[:idx]
                if before:
                    yield (before, None) if in_think else (None, before)
                buffer = buffer[idx + len(tag):]
                in_think = not in_think
                continue  # more tags might be in the same buffer

            # No full tag here yet. Hold back only a possible partial
            # match at the very end of the buffer; release the rest.
            hold = _longest_partial_match(buffer, tag)
            safe_part = buffer[: len(buffer) - hold] if hold else buffer
            if safe_part:
                yield (safe_part, None) if in_think else (None, safe_part)
            buffer = buffer[len(buffer) - hold:] if hold else ""
            break
        if stopped:
            break

    if pending_text and not stopped:
        buffer += pending_text
    if buffer:
        yield (buffer, None) if in_think else (None, buffer)

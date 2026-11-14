"""
Image generation auto-detects the model format from its path:

  - A .gguf file -> stable-diffusion.cpp, a C++ engine in the same
    family as llama.cpp. Runs quantized models on CPU with no GPU.
    Shelled out to as a compiled `sd` binary (see setup_image_gguf.sh).

  - A single .safetensors checkpoint (e.g. a model like
    "Counterfeit-V3.0_fix_fp16.safetensors" downloaded as one file
    from Civitai/Hugging Face) -> loaded directly with diffusers'
    from_single_file, no folder structure needed.

  - A folder in standard Hugging Face diffusers format (containing
    model_index.json plus unet/, vae/, text_encoder/ subfolders) ->
    loaded with diffusers' from_pretrained.

The two diffusers paths run on CPU. That is genuinely slow on an
8GB/no-GPU machine (minutes per image rather than seconds), which is
the honest tradeoff for skipping GPU/API requirements entirely.
"""

import subprocess
import time
import uuid
from pathlib import Path

from server import config_store

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "static" / "generated"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SD_BINARY = Path(__file__).resolve().parent.parent / "sd.cpp" / "build" / "bin" / "sd"

_diffusers_pipeline = None
_diffusers_pipeline_path = None

_status = {"loaded": False, "model_path": "", "error": None}


def get_status() -> dict:
    return dict(_status)


def unload() -> None:
    global _diffusers_pipeline, _diffusers_pipeline_path
    _diffusers_pipeline = None
    _diffusers_pipeline_path = None
    _status["loaded"] = False
    _status["model_path"] = ""
    _status["error"] = None
    import gc
    gc.collect()


def load(model_path: str) -> dict:
    """Makes this the active image model: for safetensors/HF formats
    this actually instantiates the pipeline now (so 'loaded' reflects
    reality); for GGUF it just validates the file and engine binary,
    since stable-diffusion.cpp is invoked fresh per image anyway."""
    global _status
    fmt = _detect_format(model_path)

    if not Path(model_path).exists():
        _status = {"loaded": False, "model_path": "", "error": "File or folder not found"}
        return get_status()

    unload()
    config_store.set_model_for_page("image", model_path)

    if fmt == "gguf":
        if not SD_BINARY.exists():
            _status = {"loaded": False, "model_path": "", "error": status_message()}
        else:
            _status = {"loaded": True, "model_path": model_path, "error": None, "format": fmt}
    elif fmt in ("safetensors", "hf"):
        try:
            import diffusers  # noqa: F401
        except ImportError:
            _status = {"loaded": False, "model_path": "", "error": status_message()}
            return get_status()
        try:
            _get_diffusers_pipeline(model_path, fmt)
            _status = {"loaded": True, "model_path": model_path, "error": None, "format": fmt}
        except Exception as e:
            _status = {"loaded": False, "model_path": "", "error": str(e)}
    else:
        _status = {"loaded": False, "model_path": "", "error": status_message()}

    return get_status()


def _detect_format(model_path: str) -> str:
    if model_path.lower().endswith(".gguf"):
        return "gguf"
    if model_path.lower().endswith(".safetensors"):
        return "safetensors"
    if Path(model_path).is_dir():
        return "hf"
    return "unknown"


def is_available() -> bool:
    cfg = config_store.load()
    model_path = cfg["models"].get("image", "")
    if not model_path or not Path(model_path).exists():
        return False
    fmt = _detect_format(model_path)
    if fmt == "gguf":
        return SD_BINARY.exists()
    if fmt in ("safetensors", "hf"):
        try:
            import diffusers  # noqa: F401
            return True
        except ImportError:
            return False
    return False


def status_message() -> str:
    cfg = config_store.load()
    model_path = cfg["models"].get("image", "")
    if not model_path or not Path(model_path).exists():
        return "No image model loaded. Load a .gguf, .safetensors, or Hugging Face model folder on the Image page."

    fmt = _detect_format(model_path)
    if fmt == "gguf" and not SD_BINARY.exists():
        return "Image engine not built yet. Run setup_image_gguf.sh to compile stable-diffusion.cpp."
    if fmt in ("safetensors", "hf"):
        try:
            import diffusers  # noqa: F401
        except ImportError:
            return "diffusers is not installed. Run: pip install diffusers accelerate safetensors"
    if fmt == "unknown":
        return "Unrecognized model file. Use a .gguf, .safetensors file, or a Hugging Face model folder."
    return "Ready."


def _get_diffusers_pipeline(model_path: str, fmt: str):
    global _diffusers_pipeline, _diffusers_pipeline_path
    if _diffusers_pipeline is not None and _diffusers_pipeline_path == model_path:
        return _diffusers_pipeline

    import torch
    from diffusers import StableDiffusionPipeline

    if fmt == "safetensors":
        pipe = StableDiffusionPipeline.from_single_file(
            model_path, torch_dtype=torch.float32, low_cpu_mem_usage=True
        )
    else:
        pipe = StableDiffusionPipeline.from_pretrained(
            model_path, torch_dtype=torch.float32, low_cpu_mem_usage=True
        )
    pipe = pipe.to("cpu")

    # Real chunked processing, not just a memory-saving gesture: attention
    # slicing runs the attention computation over the batch in smaller
    # pieces instead of all at once, and VAE slicing/tiling does the same
    # for the final image decode. Both cut peak RAM meaningfully on a
    # CPU-only machine at a small speed cost.
    pipe.enable_attention_slicing()
    if hasattr(pipe, "enable_vae_slicing"):
        pipe.enable_vae_slicing()
    if hasattr(pipe, "enable_vae_tiling"):
        pipe.enable_vae_tiling()

    _diffusers_pipeline = pipe
    _diffusers_pipeline_path = model_path
    return pipe


def _generate_gguf(model_path, prompt, steps, width, height, n_threads) -> Path:
    out_name = f"{uuid.uuid4().hex}.png"
    out_path = OUTPUT_DIR / out_name
    cmd = [
        str(SD_BINARY),
        "-m", model_path,
        "-p", prompt,
        "-o", str(out_path),
        "--steps", str(steps),
        "-W", str(width),
        "-H", str(height),
        "--threads", str(n_threads),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"Image generation failed: {result.stderr[-800:]}")
    return out_path


def _generate_diffusers(model_path, fmt, prompt, steps, width, height) -> Path:
    pipe = _get_diffusers_pipeline(model_path, fmt)
    image = pipe(prompt, num_inference_steps=steps, width=width, height=height).images[0]
    out_name = f"{uuid.uuid4().hex}.png"
    out_path = OUTPUT_DIR / out_name
    image.save(out_path)
    return out_path


def generate(prompt: str, steps: int = 20, width: int = 512, height: int = 512) -> dict:
    cfg = config_store.load()
    model_path = cfg["models"].get("image", "")
    if not model_path or not Path(model_path).exists():
        raise RuntimeError("No image model loaded")

    fmt = _detect_format(model_path)
    t0 = time.time()

    if fmt == "gguf":
        if not SD_BINARY.exists():
            raise RuntimeError(status_message())
        out_path = _generate_gguf(model_path, prompt, steps, width, height, cfg.get("n_threads", 4))
    elif fmt in ("safetensors", "hf"):
        out_path = _generate_diffusers(model_path, fmt, prompt, steps, width, height)
    else:
        raise RuntimeError(status_message())

    elapsed = round(time.time() - t0, 1)
    return {
        "url": f"/static/generated/{out_path.name}",
        "seconds": elapsed,
    }

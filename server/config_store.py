"""
Persists small pieces of state to config.json in the project root:
 - which model file was last loaded on each page (chat, coder, image)
 - the last active page
 - an optional web search API key (ignored entirely if left blank)
"""

import json
import threading
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

DEFAULTS = {
    "last_page": "chat",
    "models": {
        "chat": "",
        "coder": "",
        "image": ""
    },
    "n_ctx": 4096,
    "n_threads": 4,
    "max_ram_gb": 0,
    "search_api_key": "",
    "search_api_provider": "",
    "system_prompt": "",
    "chat_template": "",
    "stop_sequences": "<|im_end|>",
    "temperature": 0.3
}

_lock = threading.Lock()


def load() -> dict:
    with _lock:
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r") as f:
                    data = json.load(f)
                merged = {**DEFAULTS, **data}
                merged["models"] = {**DEFAULTS["models"], **data.get("models", {})}
                return merged
            except (json.JSONDecodeError, OSError):
                pass
        return dict(DEFAULTS)


def save(cfg: dict) -> None:
    with _lock:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)


def set_model_for_page(page: str, model_path: str) -> None:
    cfg = load()
    cfg["models"][page] = model_path
    save(cfg)


def set_last_page(page: str) -> None:
    cfg = load()
    cfg["last_page"] = page
    save(cfg)


def set_search_api(provider: str, key: str) -> None:
    cfg = load()
    cfg["search_api_provider"] = provider
    cfg["search_api_key"] = key
    save(cfg)

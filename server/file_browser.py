import os
from pathlib import Path

MODEL_EXTENSIONS = {".gguf", ".safetensors"}


def start_locations() -> list[dict]:
    home = str(Path.home())
    locations = [{"name": "Home", "path": home}]
    for common in ["Downloads", "Documents", "models"]:
        candidate = Path(home) / common
        if candidate.is_dir():
            locations.append({"name": common, "path": str(candidate)})
    if os.name != "nt":
        locations.append({"name": "Filesystem root", "path": "/"})
    else:
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                locations.append({"name": drive, "path": drive})
    return locations


def list_dir(path: str) -> dict:
    p = Path(path).expanduser()
    # If the model path box already contains a selectable model file, open its
    # parent directory rather than returning HTTP 400 from the folder browser.
    if p.is_file() and p.suffix.lower() in MODEL_EXTENSIONS:
        p = p.parent
    if not p.exists() or not p.is_dir():
        raise ValueError(f"Not a directory: {path}")
    p = p.resolve()

    entries = []
    try:
        children = sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
    except PermissionError:
        children = []

    for child in children:
        if child.name.startswith("."):
            continue
        is_dir = child.is_dir()
        is_model_file = (not is_dir) and child.suffix.lower() in MODEL_EXTENSIONS
        if is_dir or is_model_file:
            entries.append({
                "name": child.name,
                "path": str(child),
                "is_dir": is_dir,
            })

    parent = str(p.parent) if p.parent != p else None
    return {
        "current_path": str(p),
        "parent_path": parent,
        "entries": entries,
    }

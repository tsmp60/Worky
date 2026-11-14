"""
Coder page harness. Everything the model touches lives under
WORKSPACE_ROOT, one folder per project, so the model can never write
outside of it.

Rather than a single request/response, this runs a short agent loop:
the model can look around the project and read files across several
turns before it commits to a final answer, the same shape as how
Claude Code or Codex work through a task, just expressed as plain text
markers instead of a native tool-calling API (which most small local
GGUF models do not implement reliably):

    LIST: relative/dir (or LIST: . for the project root)
        Harness replies with that directory's contents.

    READ: relative/path/to/file.ext
        Harness replies with that file's current contents.

    SEARCH: <query>
        Harness runs a web search and replies with the results.

    FILE: relative/path/to/file.ext
        ```
        full new file contents
        ```
        One or more of these in a reply are written to disk. Existing
        files are diffed against their previous contents so the change
        is visible before and after it's applied.

Each turn, the harness looks for exactly one of LIST/READ/SEARCH first
(in that order); if none is present, the reply is treated as final and
any FILE blocks in it are applied.
"""

import difflib
import re
import shutil
import zipfile
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent / "workspace"

FILE_BLOCK_RE = re.compile(
    r"FILE:\s*(?P<path>[^\n]+)\n```[a-zA-Z0-9_+\-]*\n(?P<content>.*?)```",
    re.DOTALL,
)
SEARCH_RE = re.compile(r"^\s*SEARCH:\s*(?P<query>[^\n]+)", re.MULTILINE)
LIST_RE = re.compile(r"^\s*LIST:\s*(?P<path>[^\n]+)", re.MULTILINE)
READ_RE = re.compile(r"^\s*READ:\s*(?P<path>[^\n]+)", re.MULTILINE)

MAX_AGENT_ITERATIONS = 6


def _project_dir(project: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", project) or "default"
    p = WORKSPACE_ROOT / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_projects() -> list[str]:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in WORKSPACE_ROOT.iterdir() if p.is_dir()])


def list_files(project: str) -> list[str]:
    root = _project_dir(project)
    files = []
    for p in root.rglob("*"):
        if p.is_file():
            files.append(str(p.relative_to(root)))
    return sorted(files)


def file_tree(project: str) -> list[dict]:
    """Nested {name, path, is_dir, children} structure for the sidebar
    file tree, folders first then files, both alphabetical."""
    root = _project_dir(project)

    def build(dir_path: Path) -> list[dict]:
        nodes = []
        try:
            children = sorted(dir_path.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
        except PermissionError:
            children = []
        for child in children:
            if child.name.startswith("."):
                continue
            rel = str(child.relative_to(root))
            if child.is_dir():
                nodes.append({
                    "name": child.name, "path": rel, "is_dir": True,
                    "children": build(child),
                })
            else:
                nodes.append({"name": child.name, "path": rel, "is_dir": False})
        return nodes

    return build(root)


def list_dir_for_model(project: str, rel_path: str) -> str:
    """Plain-text directory listing fed back to the model for a LIST: request."""
    target = _project_dir(project) if rel_path.strip() in (".", "", "/") else _resolve(project, rel_path)
    if not target.exists():
        return f"Directory not found: {rel_path}"
    if not target.is_dir():
        return f"Not a directory: {rel_path}"
    root = _project_dir(project)
    lines = []
    for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        if child.name.startswith("."):
            continue
        rel = child.relative_to(root)
        lines.append(f"{'[dir] ' if child.is_dir() else ''}{rel}")
    return "\n".join(lines) if lines else "(empty directory)"


def read_file(project: str, rel_path: str) -> str:
    target = _resolve(project, rel_path)
    return target.read_text(errors="replace")


def write_file(project: str, rel_path: str, content: str) -> None:
    target = _resolve(project, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def _resolve(project: str, rel_path: str) -> Path:
    root = _project_dir(project)
    target = (root / rel_path).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError("Path escapes the project sandbox")
    return target


def save_uploaded_file(project: str, filename: str, file_bytes: bytes) -> str:
    safe_name = Path(filename).name  # strip any directory component
    target = _project_dir(project) / safe_name
    target.write_bytes(file_bytes)
    return safe_name


def zip_project(project: str) -> Path:
    root = _project_dir(project)
    zip_path = WORKSPACE_ROOT / f"{root.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in root.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(root))
    return zip_path


def delete_project(project: str) -> None:
    root = _project_dir(project)
    shutil.rmtree(root, ignore_errors=True)


def extract_action(model_output: str) -> dict | None:
    """Looks for exactly one of LIST/READ/SEARCH in a reply, checked in
    that priority order. Returns None if the reply has none of them,
    meaning it should be treated as the agent's final answer."""
    m = LIST_RE.search(model_output)
    if m:
        return {"type": "list", "path": m.group("path").strip()}
    m = READ_RE.search(model_output)
    if m:
        return {"type": "read", "path": m.group("path").strip()}
    m = SEARCH_RE.search(model_output)
    if m:
        return {"type": "search", "query": m.group("query").strip()}
    return None


def apply_file_blocks(project: str, model_output: str) -> list[dict]:
    """Writes every FILE: block found in the model's reply to disk.
    Returns one entry per file with a unified diff against whatever
    was there before (or a flag marking it as newly created)."""
    results = []
    for match in FILE_BLOCK_RE.finditer(model_output):
        rel_path = match.group("path").strip()
        new_content = match.group("content")

        try:
            old_content = read_file(project, rel_path)
            is_new = False
        except (FileNotFoundError, OSError):
            old_content = ""
            is_new = True

        write_file(project, rel_path, new_content)

        diff_lines = list(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
        ))
        results.append({
            "path": rel_path,
            "is_new": is_new,
            "diff": "".join(diff_lines),
            "lines": len(new_content.splitlines()),
        })
    return results


SYSTEM_PROMPT = """You are the Coder assistant inside Worky, a local development harness.
You work in short steps, looking around the project before you change anything,
the same way a careful engineer would.

You have four actions available. Use exactly one of LIST, READ, or SEARCH per
reply when you need more information, and nothing else in that reply:

LIST: relative/dir
    Reply with only this line to see what's inside a folder. Use "LIST: ."
    for the project root.

READ: relative/path/to/file.ext
    Reply with only this line to see a file's current contents before you
    change it. Always read a file before editing it if you have not already
    seen its current contents this conversation.

SEARCH: your query here
    Reply with only this line if you need current information you're not
    confident about (a library's API, current best practice, a version
    number).

When you are ready to finish, reply with a brief explanation in plain text
plus one FILE block for each file you are creating or changing:

FILE: relative/path/to/file.ext
```
full file contents, not a diff or excerpt
```

Do not include a LIST, READ, or SEARCH line in the same reply as a FILE
block. Do not truncate file contents. Only include files you are actually
changing.
"""

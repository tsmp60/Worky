import json
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, Response

from server import chat_db, config_store, coder_harness, file_browser, image_gen, model_manager, web_search

ROOT = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)

chat_db.init_db()

# In-memory handoff buffer: set by the "Send to" action on the Chat page,
# read once by whichever page it targets, then cleared.
_handoff = {"target": None, "prompt": None}


# ---------------------------------------------------------------- pages --
@app.route("/")
def index():
    cfg = config_store.load()
    return render_template("index.html", last_page=cfg.get("last_page", "chat"))


@app.route("/api/state/last_page", methods=["GET", "POST"])
def last_page():
    if request.method == "POST":
        page = request.json.get("page", "chat")
        config_store.set_last_page(page)
        return jsonify({"ok": True})
    return jsonify({"page": config_store.load().get("last_page", "chat")})


# --------------------------------------------------------------- models --
@app.route("/api/model/status/<page>")
def model_status(page):
    cfg = config_store.load()
    if page == "image":
        status = image_gen.get_status()
    else:
        status = model_manager.get_status(page)
    return jsonify({
        "status": status,
        "remembered_model": cfg["models"].get(page, ""),
        "n_threads": cfg.get("n_threads"),
        "n_ctx": cfg.get("n_ctx"),
        "max_ram_gb": cfg.get("max_ram_gb", 0),
    })


@app.route("/api/model/load", methods=["POST"])
def model_load():
    data = request.json
    page = data["page"]
    model_path = data["model_path"]

    if page == "image":
        status = image_gen.load(model_path)
        return jsonify(status)

    status = model_manager.load(page, model_path)
    return jsonify(status)


@app.route("/api/model/unload", methods=["POST"])
def model_unload():
    page = request.json["page"]
    if page == "image":
        image_gen.unload()
    else:
        model_manager.unload(page)
    return jsonify({"ok": True})


@app.route("/api/browse/start")
def browse_start():
    return jsonify(file_browser.start_locations())


@app.route("/api/browse")
def browse():
    path = request.args.get("path") or str(Path.home())
    try:
        return jsonify(file_browser.list_dir(path))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/settings/search_api", methods=["POST"])
def set_search_api():
    data = request.json
    config_store.set_search_api(data.get("provider", ""), data.get("api_key", ""))
    return jsonify({"ok": True})


@app.route("/api/settings/chat", methods=["GET", "POST"])
def chat_settings():
    if request.method == "GET":
        cfg = config_store.load()
        return jsonify({key: cfg.get(key, config_store.DEFAULTS.get(key, "")) for key in
                        ("system_prompt", "chat_template", "stop_sequences", "temperature")})
    data = request.json or {}
    cfg = config_store.load()
    cfg["system_prompt"] = str(data.get("system_prompt", cfg.get("system_prompt", "")))[:20000]
    cfg["chat_template"] = str(data.get("chat_template", cfg.get("chat_template", "")))[:20000]
    cfg["stop_sequences"] = str(data.get("stop_sequences", cfg.get("stop_sequences", "<|im_end|>")))[:2000]
    try:
        cfg["temperature"] = min(2.0, max(0.0, float(data.get("temperature", cfg.get("temperature", 0.3)))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Temperature must be a number between 0 and 2."}), 400
    config_store.save(cfg)
    return jsonify({"ok": True})


@app.route("/api/settings/runtime", methods=["POST"])
def set_runtime():
    data = request.json
    cfg = config_store.load()
    cfg["n_threads"] = int(data.get("n_threads", cfg["n_threads"]))
    cfg["n_ctx"] = int(data.get("n_ctx", cfg["n_ctx"]))
    cfg["max_ram_gb"] = float(data.get("max_ram_gb", cfg.get("max_ram_gb", 0)))
    config_store.save(cfg)
    return jsonify({"ok": True})


# ---------------------------------------------------------- conversations --
@app.route("/api/conversations/<page>", methods=["GET", "POST"])
def conversations(page):
    if request.method == "POST":
        conv_id = chat_db.create_conversation(page)
        return jsonify({"id": conv_id})
    return jsonify(chat_db.list_conversations(page))


@app.route("/api/conversations/<int:conv_id>/messages", methods=["GET"])
def conversation_messages(conv_id):
    return jsonify(chat_db.get_messages(conv_id))


@app.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    chat_db.delete_conversation(conv_id)
    return jsonify({"ok": True})


@app.route("/api/conversations/<int:conv_id>/rename", methods=["POST"])
def rename_conversation(conv_id):
    chat_db.rename_conversation(conv_id, request.json["title"])
    return jsonify({"ok": True})


# ------------------------------------------------------------------ chat --
@app.route("/api/chat/send", methods=["POST"])
def chat_send():
    data = request.json
    conv_id = data["conversation_id"]
    user_message = data["message"]
    use_search = data.get("use_search", False)

    chat_db.add_message(conv_id, "user", user_message)
    history = chat_db.get_messages(conv_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    chat_cfg = config_store.load()
    system_prompt = chat_cfg.get("system_prompt", "").strip()
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    if use_search:
        results = web_search.search(user_message)
        context = web_search.format_results_for_model(results)
        messages.append({
            "role": "system",
            "content": f"{context}\n\nUse the above search results if relevant when answering."
        })

    def generate():
        full_content, full_reasoning = "", ""
        try:
            for reasoning_delta, content_delta in model_manager.chat_complete(
                "chat", messages, temperature=float(chat_cfg.get("temperature", 0.3))):
                if reasoning_delta:
                    full_reasoning += reasoning_delta
                    yield f"data: {json.dumps({'type': 'reasoning', 'text': reasoning_delta})}\n\n"
                if content_delta:
                    full_content += content_delta
                    yield f"data: {json.dumps({'type': 'content', 'text': content_delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
            return
        chat_db.add_message(conv_id, "assistant", full_content, full_reasoning or None)
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


# ----------------------------------------------------------------- coder --
@app.route("/api/coder/projects", methods=["GET", "POST"])
def coder_projects():
    if request.method == "POST":
        name = request.json.get("name", "project")
        coder_harness._project_dir(name)  # creates it
        return jsonify({"ok": True})
    return jsonify(coder_harness.list_projects())


@app.route("/api/coder/projects/<project>", methods=["DELETE"])
def coder_delete_project(project):
    coder_harness.delete_project(project)
    return jsonify({"ok": True})


@app.route("/api/coder/files/<project>")
def coder_files(project):
    return jsonify(coder_harness.list_files(project))


@app.route("/api/coder/tree/<project>")
def coder_tree(project):
    return jsonify(coder_harness.file_tree(project))


@app.route("/api/coder/file/<project>")
def coder_read_file(project):
    rel_path = request.args.get("path")
    try:
        return jsonify({"content": coder_harness.read_file(project, rel_path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/coder/file/<project>", methods=["POST"])
def coder_write_file(project):
    data = request.json
    coder_harness.write_file(project, data["path"], data["content"])
    return jsonify({"ok": True})


@app.route("/api/coder/upload/<project>", methods=["POST"])
def coder_upload(project):
    f = request.files["file"]
    name = coder_harness.save_uploaded_file(project, f.filename, f.read())
    return jsonify({"filename": name})


@app.route("/api/coder/download/<project>")
def coder_download(project):
    zip_path = coder_harness.zip_project(project)
    return send_file(zip_path, as_attachment=True, download_name=f"{project}.zip")


@app.route("/api/coder/ask", methods=["POST"])
def coder_ask():
    data = request.json
    project = data["project"]
    conv_id = data["conversation_id"]
    user_message = data["message"]

    chat_db.add_message(conv_id, "user", user_message)

    files = coder_harness.list_files(project)
    file_summary = "\n".join(f"- {f}" for f in files) or "(no files yet)"
    history = chat_db.get_messages(conv_id)
    messages = [{"role": "system", "content": coder_harness.SYSTEM_PROMPT}]
    messages.append({"role": "system", "content": f"Current project files:\n{file_summary}"})
    messages.extend({"role": m["role"], "content": m["content"]} for m in history if m["role"] != "system")

    def run_once(msgs):
        content = ""
        for _, content_delta in model_manager.chat_complete("coder", msgs, max_tokens=2048):
            if content_delta:
                content += content_delta
        return content

    activity = []
    final_reply = ""

    for _ in range(coder_harness.MAX_AGENT_ITERATIONS):
        reply = run_once(messages)
        action = coder_harness.extract_action(reply)

        if action is None:
            final_reply = reply
            break

        messages.append({"role": "assistant", "content": reply})

        if action["type"] == "list":
            result_text = coder_harness.list_dir_for_model(project, action["path"])
            activity.append({"type": "list", "path": action["path"]})
            messages.append({"role": "system", "content": f"Contents of {action['path']}:\n{result_text}"})

        elif action["type"] == "read":
            try:
                content = coder_harness.read_file(project, action["path"])
                activity.append({"type": "read", "path": action["path"]})
                messages.append({"role": "system", "content": f"Contents of {action['path']}:\n\n{content}"})
            except Exception as e:
                messages.append({"role": "system", "content": f"Could not read {action['path']}: {e}"})

        elif action["type"] == "search":
            results = web_search.search(action["query"])
            context = web_search.format_results_for_model(results)
            activity.append({"type": "search", "query": action["query"]})
            messages.append({"role": "system", "content": context})
    else:
        final_reply = "Reached the step limit for this task without a final answer. " \
                       "Try breaking the request into smaller steps."

    file_changes = coder_harness.apply_file_blocks(project, final_reply)
    for fc in file_changes:
        activity.append({"type": "write", "path": fc["path"], "is_new": fc["is_new"], "diff": fc["diff"]})

    chat_db.add_message(conv_id, "assistant", final_reply)

    return jsonify({"reply": final_reply, "activity": activity, "files_written": [f["path"] for f in file_changes]})


# ----------------------------------------------------------------- image --
@app.route("/api/image/status")
def image_status():
    return jsonify({"available": image_gen.is_available(), "message": image_gen.status_message()})


@app.route("/api/image/generate", methods=["POST"])
def generate_image():
    data = request.json
    try:
        result = image_gen.generate(
            data["prompt"],
            steps=int(data.get("steps", 20)),
            width=int(data.get("width", 512)),
            height=int(data.get("height", 512)),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# --------------------------------------------------------------- handoff --
@app.route("/api/handoff", methods=["POST"])
def handoff_set():
    data = request.json
    conv_id = data["conversation_id"]
    target = data["target"]  # 'coder' or 'image'

    history = chat_db.get_messages(conv_id)
    transcript = "\n\n".join(f"{m['role']}: {m['content']}" for m in history)

    if target == "image":
        prompt = (
            "Based on this conversation, write a single, self contained image "
            "generation prompt that captures what was discussed:\n\n" + transcript
        )
    else:
        prompt = (
            "Based on this conversation, summarize what should be built as a "
            "clear, actionable set of instructions for a coding assistant:\n\n" + transcript
        )

    _handoff["target"] = target
    _handoff["prompt"] = prompt
    return jsonify({"ok": True})


@app.route("/api/handoff/consume")
def handoff_consume():
    data = dict(_handoff)
    _handoff["target"] = None
    _handoff["prompt"] = None
    return jsonify(data)


def _open_browser():
    webbrowser.open("http://127.0.0.1:5050")


def main():
    threading.Timer(1.0, _open_browser).start()
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)


if __name__ == "__main__":
    main()

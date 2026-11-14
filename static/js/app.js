const state = {
  page: document.body.dataset.lastPage || "chat",
  conversationId: { chat: null, coder: null },
  currentProject: null,
  currentFile: null,
};

const el = (id) => document.getElementById(id);

// ------------------------------------------------------------- page switch --
async function setPage(page) {
  const previousPage = state.page;

  // Free the outgoing page's model from RAM before switching, so it is
  // never sitting in memory alongside the page you're about to load.
  if (previousPage && previousPage !== page) {
    await unloadPageModel(previousPage);
  }

  state.page = page;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  document.querySelectorAll(".page").forEach((p) => (p.style.display = "none"));
  el(`page-${page}`).style.display = "flex";

  document.getElementById("history-section").style.display = page === "image" ? "none" : "block";
  document.getElementById("reasoning-section").style.display = page === "image" ? "none" : "block";

  fetch("/api/state/last_page", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page }),
  });

  refreshModelPanel();
  if (page === "chat" || page === "coder") refreshConversationList();
  if (page === "coder") refreshProjects();
  if (page === "image") refreshImageStatus();
}

async function unloadPageModel(page) {
  try {
    await fetch("/api/model/unload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page }),
    });
  } catch (e) {
    // best effort; if this fails the next load still overwrites it
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => setPage(btn.dataset.page));
});

// If the browser tab is hidden (minimized, switched away from), free the
// current page's model too, since "inactive" isn't only about which page
// you're on inside Worky. Reload it automatically when you come back.
document.addEventListener("visibilitychange", async () => {
  if (document.hidden) {
    await unloadPageModel(state.page);
  } else {
    refreshModelPanel();
  }
});

// -------------------------------------------------------------- model panel --
async function refreshModelPanel() {
  const page = state.page;
  const res = await fetch(`/api/model/status/${page}`);
  const data = await res.json();
  el("model-path-input").value = data.remembered_model || "";
  el("n-threads-input").value = data.n_threads ?? 4;
  el("n-ctx-input").value = data.n_ctx ?? 4096;
  el("max-ram-input").value = data.max_ram_gb ?? 0;
  renderModelStatus(data.status);

  // If this page has a remembered model but nothing is loaded into memory
  // yet (fresh server start, or just switched here for the first time),
  // load it automatically now.
  if (!data.status.loaded && data.remembered_model) {
    el("model-status").textContent = "Loading remembered model...";
    const loadRes = await fetch("/api/model/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page, model_path: data.remembered_model }),
    });
    const status = await loadRes.json();
    renderModelStatus(status);
    if (page === "image") refreshImageStatus();
  }
}

function renderModelStatus(status) {
  const statusEl = el("model-status");
  if (status && status.loaded) {
    statusEl.textContent = `Loaded: ${status.model_path}` +
      (status.load_seconds ? ` (${status.load_seconds}s)` : "");
  } else if (status && status.error) {
    statusEl.textContent = `Error: ${status.error}`;
  } else if (status && status.note) {
    statusEl.textContent = status.note;
  } else {
    statusEl.textContent = "No model loaded";
  }
}

el("load-model-btn").addEventListener("click", async () => {
  const model_path = el("model-path-input").value.trim();
  if (!model_path) return;
  el("model-status").textContent = "Loading...";
  const loadRes = await fetch("/api/model/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: state.page, model_path }),
  });
  const loadStatus = await loadRes.json();
  renderModelStatus(loadStatus);
  refreshModelPanel();
  if (state.page === "image") refreshImageStatus();
});

// ------------------------------------------------------------ file browser --
let browseCurrentPath = null;

el("browse-model-btn").addEventListener("click", async () => {
  el("browse-modal").style.display = "flex";
  const shortcuts = await (await fetch("/api/browse/start")).json();
  const shortcutsBox = el("browse-shortcuts");
  shortcutsBox.innerHTML = "";
  shortcuts.forEach((loc) => {
    const btn = document.createElement("button");
    btn.textContent = loc.name;
    btn.addEventListener("click", () => loadBrowseDir(loc.path));
    shortcutsBox.appendChild(btn);
  });
  const startPath = el("model-path-input").value.trim();
  loadBrowseDir(null, startPath);
});

el("browse-close-btn").addEventListener("click", () => {
  el("browse-modal").style.display = "none";
});

el("browse-select-folder-btn").addEventListener("click", () => {
  if (browseCurrentPath) {
    el("model-path-input").value = browseCurrentPath;
  }
  el("browse-modal").style.display = "none";
});

async function loadBrowseDir(path, fallbackPath) {
  const target = path || fallbackPath || "";
  const res = await fetch(`/api/browse?path=${encodeURIComponent(target)}`);
  const data = await res.json();
  if (data.error) return;

  browseCurrentPath = data.current_path;
  el("browse-current-path").textContent = data.current_path;

  const list = el("browse-list");
  list.innerHTML = "";

  if (data.parent_path) {
    const up = document.createElement("div");
    up.className = "browse-item parent";
    up.innerHTML = `<span class="icon">..</span><span>Up one level</span>`;
    up.addEventListener("click", () => loadBrowseDir(data.parent_path));
    list.appendChild(up);
  }

  data.entries.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "browse-item";
    row.innerHTML = `<span class="icon">${entry.is_dir ? "\u25B8" : "\u25CF"}</span><span>${escapeHtml(entry.name)}</span>`;
    row.addEventListener("click", () => {
      if (entry.is_dir) {
        loadBrowseDir(entry.path);
      } else {
        el("model-path-input").value = entry.path;
        el("browse-modal").style.display = "none";
      }
    });
    list.appendChild(row);
  });
}

el("unload-model-btn").addEventListener("click", async () => {
  await fetch("/api/model/unload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: state.page }),
  });
  refreshModelPanel();
});

// -------------------------------------------------------------- search settings --
el("save-search-settings").addEventListener("click", async () => {
  await fetch("/api/settings/search_api", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: el("search-provider").value,
      api_key: el("search-api-key").value.trim(),
    }),
  });
});

el("save-runtime-settings").addEventListener("click", async () => {
  await fetch("/api/settings/runtime", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      n_threads: el("n-threads-input").value.trim() || 4,
      n_ctx: el("n-ctx-input").value.trim() || 4096,
      max_ram_gb: el("max-ram-input").value.trim() || 0,
    }),
  });
});

async function loadChatSettings() {
  try {
    const res = await fetch("/api/settings/chat");
    const cfg = await res.json();
    el("system-prompt-input").value = cfg.system_prompt || "";
    el("chat-template-input").value = cfg.chat_template || "";
    el("stop-sequences-input").value = cfg.stop_sequences ?? "<|im_end|>";
    el("temperature-input").value = cfg.temperature ?? 0.3;
  } catch (error) {
    el("chat-settings-status").textContent = "Could not load chat settings.";
  }
}

el("save-chat-settings").addEventListener("click", async () => {
  const status = el("chat-settings-status");
  status.textContent = "Saving…";
  try {
    const res = await fetch("/api/settings/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        system_prompt: el("system-prompt-input").value,
        chat_template: el("chat-template-input").value,
        stop_sequences: el("stop-sequences-input").value,
        temperature: el("temperature-input").value,
      }),
    });
    const result = await res.json();
    if (!res.ok || !result.ok) throw new Error(result.error || "Could not save settings");
    status.textContent = "Chat settings saved.";
  } catch (error) {
    status.textContent = "Save failed: " + error.message;
  }
});
loadChatSettings();

// ------------------------------------------------------------------ history --
async function refreshConversationList() {
  const page = state.page;
  if (page !== "chat" && page !== "coder") return;
  const res = await fetch(`/api/conversations/${page}`);
  const list = await res.json();
  const container = el("conversation-list");
  container.innerHTML = "";
  list.forEach((c) => {
    const item = document.createElement("div");
    item.className = "conversation-item" + (c.id === state.conversationId[page] ? " active" : "");
    item.innerHTML = `<span class="title">${escapeHtml(c.title)}</span><span class="delete-x">&times;</span>`;
    item.querySelector(".title").addEventListener("click", () => openConversation(page, c.id));
    item.querySelector(".delete-x").addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/api/conversations/${c.id}`, { method: "DELETE" });
      if (state.conversationId[page] === c.id) state.conversationId[page] = null;
      refreshConversationList();
    });
    container.appendChild(item);
  });
}

async function openConversation(page, id) {
  state.conversationId[page] = id;
  const res = await fetch(`/api/conversations/${id}/messages`);
  const messages = await res.json();

  if (page === "chat") {
    const box = el("chat-messages");
    box.innerHTML = "";
    messages.forEach((m) => {
      if (m.role === "system") return;
      appendMessage(box, m.role, m.content);
    });
  } else {
    const log = el("activity-log");
    log.innerHTML = "";
    messages.forEach((m) => {
      if (m.role === "system") return;
      appendActivityMessage(m.role, m.content);
    });
  }
  refreshConversationList();
}

async function ensureConversation(page) {
  if (state.conversationId[page]) return state.conversationId[page];
  const res = await fetch(`/api/conversations/${page}`, { method: "POST" });
  const data = await res.json();
  state.conversationId[page] = data.id;
  refreshConversationList();
  return data.id;
}

el("new-conversation-btn").addEventListener("click", async () => {
  const page = state.page;
  const res = await fetch(`/api/conversations/${page}`, { method: "POST" });
  const data = await res.json();
  state.conversationId[page] = data.id;
  el(page === "chat" ? "chat-messages" : "activity-log").innerHTML = "";
  refreshConversationList();
});

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function appendMessage(box, role, text) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

// --------------------------------------------------------------------- chat --
el("chat-send-btn").addEventListener("click", sendChatMessage);
el("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});

async function sendChatMessage() {
  const input = el("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";

  const convId = await ensureConversation("chat");
  const box = el("chat-messages");
  appendMessage(box, "user", text);
  const assistantDiv = appendMessage(box, "assistant", "");
  el("reasoning-box").textContent = "";

  const res = await fetch("/api/chat/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: convId,
      message: text,
      use_search: el("use-search-toggle").checked,
    }),
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      if (!part.startsWith("data: ")) continue;
      const payload = JSON.parse(part.slice(6));
      if (payload.type === "content") {
        assistantDiv.textContent += payload.text;
        box.scrollTop = box.scrollHeight;
      } else if (payload.type === "reasoning") {
        el("reasoning-box").textContent += payload.text;
      } else if (payload.type === "error") {
        assistantDiv.textContent += `\n[error: ${payload.text}]`;
      }
    }
  }
  refreshConversationList();
}

// ------------------------------------------------------------------ handoff --
el("handoff-btn").addEventListener("click", () => {
  el("handoff-menu").classList.toggle("open");
});

document.querySelectorAll("#handoff-menu button").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const target = btn.dataset.target;
    el("handoff-menu").classList.remove("open");
    const convId = state.conversationId.chat;
    if (!convId) return;
    await fetch("/api/handoff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: convId, target }),
    });
    setPage(target);
    const res = await fetch("/api/handoff/consume");
    const data = await res.json();
    if (data.prompt) {
      if (target === "image") el("image-prompt").value = data.prompt;
      if (target === "coder") el("coder-input").value = data.prompt;
    }
  });
});

// ----------------------------------------------------------------- coder --
let codeEditor = null;

function getCodeMirrorModeFor(filename) {
  const ext = (filename.split(".").pop() || "").toLowerCase();
  const map = {
    py: "python", js: "javascript", jsx: "javascript", ts: "javascript",
    json: "javascript", html: "htmlmixed", htm: "htmlmixed", xml: "xml",
    css: "css", c: "text/x-csrc", h: "text/x-csrc", cpp: "text/x-c++src",
    hpp: "text/x-c++src", java: "text/x-java", md: "markdown",
    sh: "shell", bash: "shell",
  };
  return map[ext] || "";
}

function ensureEditor() {
  if (codeEditor) return codeEditor;
  codeEditor = CodeMirror(el("editor-host"), {
    value: "",
    lineNumbers: true,
    theme: "eclipse",
    viewportMargin: Infinity,
  });
  return codeEditor;
}

async function refreshProjects() {
  const res = await fetch("/api/coder/projects");
  const projects = await res.json();
  const select = el("project-select");
  select.innerHTML = "";
  if (projects.length === 0) projects.push("default");
  projects.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    select.appendChild(opt);
  });
  state.currentProject = select.value || "default";
  refreshFileTree();
}

el("project-select").addEventListener("change", (e) => {
  state.currentProject = e.target.value;
  state.currentFile = null;
  refreshFileTree();
});

el("new-project-btn").addEventListener("click", async () => {
  const name = prompt("Project name");
  if (!name) return;
  await fetch("/api/coder/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  refreshProjects();
});

async function refreshFileTree() {
  const res = await fetch(`/api/coder/tree/${state.currentProject}`);
  const tree = await res.json();
  const container = el("file-tree");
  container.innerHTML = "";
  container.appendChild(renderTreeNodes(tree));
}

function renderTreeNodes(nodes) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";
  nodes.forEach((node) => {
    const row = document.createElement("div");
    row.className = "tree-row" + (!node.is_dir && node.path === state.currentFile ? " active-file" : "");
    row.innerHTML = `<span class="icon">${node.is_dir ? "\u25B8" : "\u25CF"}</span><span>${escapeHtml(node.name)}</span>`;

    if (node.is_dir) {
      const childWrap = document.createElement("div");
      childWrap.className = "tree-children";
      childWrap.appendChild(renderTreeNodes(node.children || []));
      childWrap.style.display = "none";
      row.addEventListener("click", () => {
        childWrap.style.display = childWrap.style.display === "none" ? "block" : "none";
      });
      wrapper.appendChild(row);
      wrapper.appendChild(childWrap);
    } else {
      row.addEventListener("click", () => openFile(node.path));
      wrapper.appendChild(row);
    }
  });
  return wrapper;
}

async function openFile(path) {
  state.currentFile = path;
  const res = await fetch(`/api/coder/file/${state.currentProject}?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  el("editor-path").textContent = path;
  const editor = ensureEditor();
  const mode = getCodeMirrorModeFor(path);
  if (mode) editor.setOption("mode", mode);
  editor.setValue(data.content || "");
  refreshFileTree();
}

el("save-file-btn").addEventListener("click", async () => {
  if (!state.currentFile || !codeEditor) return;
  await fetch(`/api/coder/file/${state.currentProject}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: state.currentFile, content: codeEditor.getValue() }),
  });
});

el("upload-btn").addEventListener("click", () => el("upload-input").click());
el("upload-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  await fetch(`/api/coder/upload/${state.currentProject}`, { method: "POST", body: formData });
  refreshFileTree();
});

el("download-btn").addEventListener("click", () => {
  window.location = `/api/coder/download/${state.currentProject}`;
});

// -------------------------------------------------------- activity log --
function appendActivityMessage(role, text) {
  const log = el("activity-log");
  const div = document.createElement("div");
  div.className = `activity-entry ${role === "user" ? "user-msg" : "assistant-msg"}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function appendActivityStep(label) {
  const log = el("activity-log");
  const div = document.createElement("div");
  div.className = "activity-step";
  div.innerHTML = `<span class="dot"></span><span></span>`;
  div.querySelector("span:last-child").textContent = label;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function appendDiffBlock(entry) {
  const log = el("activity-log");
  const block = document.createElement("div");
  block.className = "diff-block";

  const header = document.createElement("div");
  header.className = "diff-header";
  header.textContent = entry.is_new ? `New file: ${entry.path}` : `Modified: ${entry.path}`;
  block.appendChild(header);

  const body = document.createElement("div");
  body.className = "diff-body";

  if (entry.is_new || !entry.diff) {
    const line = document.createElement("div");
    line.className = "diff-line ctx";
    line.textContent = entry.is_new ? "(new file created)" : "(no textual change detected)";
    body.appendChild(line);
  } else {
    entry.diff.split("\n").forEach((raw) => {
      if (!raw) return;
      const line = document.createElement("div");
      let cls = "ctx";
      if (raw.startsWith("+++") || raw.startsWith("---") || raw.startsWith("@@")) cls = "meta";
      else if (raw.startsWith("+")) cls = "add";
      else if (raw.startsWith("-")) cls = "del";
      line.className = `diff-line ${cls}`;
      line.textContent = raw;
      body.appendChild(line);
    });
  }

  block.appendChild(body);
  log.appendChild(block);
  log.scrollTop = log.scrollHeight;
}

function renderActivity(activity) {
  activity.forEach((step) => {
    if (step.type === "list") appendActivityStep(`Looking at ${step.path}`);
    else if (step.type === "read") appendActivityStep(`Reading ${step.path}`);
    else if (step.type === "search") appendActivityStep(`Searching: ${step.query}`);
    else if (step.type === "write") appendDiffBlock(step);
  });
}

el("coder-send-btn").addEventListener("click", sendCoderMessage);
el("coder-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendCoderMessage();
  }
});

async function sendCoderMessage() {
  const input = el("coder-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";

  const convId = await ensureConversation("coder");
  appendActivityMessage("user", text);
  const workingStep = appendActivityStep("Working...");

  let data;
  try {
    const res = await fetch("/api/coder/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: state.currentProject, conversation_id: convId, message: text }),
    });
    data = await res.json();
  } catch (e) {
    workingStep.querySelector("span:last-child").textContent = "Request failed: " + e;
    return;
  }

  workingStep.remove();

  if (data.activity && data.activity.length) {
    renderActivity(data.activity);
  }
  appendActivityMessage("assistant", data.reply || data.error || "No response");

  if (data.files_written && data.files_written.length) {
    refreshFileTree();
    if (data.files_written.includes(state.currentFile)) {
      openFile(state.currentFile);
    }
  }
  refreshConversationList();
}

// ------------------------------------------------------------------ image --
async function refreshImageStatus() {
  const res = await fetch("/api/image/status");
  const data = await res.json();
  el("image-status").textContent = data.message;
}

el("image-generate-btn").addEventListener("click", async () => {
  const prompt = el("image-prompt").value.trim();
  if (!prompt) return;
  const resultBox = el("image-result");
  resultBox.innerHTML = "Generating, this can take a while on CPU...";
  try {
    const res = await fetch("/api/image/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    const data = await res.json();
    if (data.error) {
      resultBox.innerHTML = escapeHtml(data.error);
    } else {
      resultBox.innerHTML = `<img src="${data.url}"><div style="width:100%;text-align:center;font-size:12px;color:var(--text-muted);margin-top:6px;">${data.seconds}s</div>`;
    }
  } catch (e) {
    resultBox.innerHTML = "Generation failed: " + e;
  }
});

// ------------------------------------------------------------------- init --
setPage(state.page);

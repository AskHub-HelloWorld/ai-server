"use strict";

const COPY_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const CHECK_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

const state = {
  currentSessionId: null,
  sessions: [],
  attachedFiles: [],
  isSending: false,
  streamingText: "",
};

const els = {
  userIdInput: document.querySelector("#userIdInput"),
  teamIdInput: document.querySelector("#teamIdInput"),
  healthCheckButton: document.querySelector("#healthCheckButton"),
  newChatButton: document.querySelector("#newChatButton"),
  refreshSessionsButton: document.querySelector("#refreshSessionsButton"),
  sessionList: document.querySelector("#sessionList"),
  connectionStatus: document.querySelector("#connectionStatus"),
  sessionTitle: document.querySelector("#sessionTitle"),
  messages: document.querySelector("#messages"),
  attachedFiles: document.querySelector("#attachedFiles"),
  fileInput: document.querySelector("#fileInput"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
};

/* ── Utilities ── */

function getUserId() {
  const value = Number.parseInt(els.userIdInput.value, 10);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error("User ID를 입력하세요.");
  }
  return value;
}

function getTeamId() {
  const raw = els.teamIdInput.value.trim();
  if (!raw) {
    return null;
  }
  const value = Number.parseInt(raw, 10);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error("Team ID는 비워두거나 1 이상의 숫자로 입력하세요.");
  }
  return value;
}

function buildUrl(path, query = "") {
  return `/api${path}${query ? `?${query}` : ""}`;
}

function setStatus(message, type = "") {
  els.connectionStatus.textContent = message;
  els.connectionStatus.classList.toggle("ok", type === "ok");
  els.connectionStatus.classList.toggle("error", type === "error");
}

function setBusy(isBusy) {
  state.isSending = isBusy;
  els.sendButton.disabled = isBusy;
  els.fileInput.disabled = isBusy;
  els.messageInput.disabled = isBusy;
}

function formatError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function getTestContextHeaders() {
  const userId = getUserId();
  const teamId = getTeamId();
  const headers = {
    "X-Test-User-Id": String(userId),
  };
  if (teamId !== null) {
    headers["X-Test-Team-Id"] = String(teamId);
  }
  return headers;
}

/* ── API ── */

async function apiFetch(path, options = {}) {
  const method = options.method || "GET";
  const query = options.query || "";
  const headers = new Headers(options.headers || {});
  for (const [key, value] of Object.entries(getTestContextHeaders())) {
    headers.set(key, value);
  }

  const response = await fetch(buildUrl(path, query), {
    ...options,
    method,
    headers,
  });

  if (!response.ok) {
    const detail = await readErrorBody(response);
    throw new Error(`${response.status} ${response.statusText}${detail ? ` - ${detail}` : ""}`);
  }
  return response;
}

async function readErrorBody(response) {
  const contentType = response.headers.get("content-type") || "";
  try {
    if (contentType.includes("application/json")) {
      const body = await response.json();
      if (typeof body.detail === "string") {
        return body.detail;
      }
      return JSON.stringify(body);
    }
    return await response.text();
  } catch {
    return "";
  }
}

/* ── Health / Sessions ── */

async function healthCheck() {
  try {
    const response = await fetch(buildUrl("/health"));
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    const body = await response.json();
    setStatus(`${body.status || "ok"} · ${body.version || "unknown"}`, "ok");
  } catch (error) {
    setStatus(formatError(error), "error");
  }
}

async function createSession() {
  const response = await apiFetch("/v1/chat/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const session = await response.json();
  state.currentSessionId = session.session_id;
  await loadSessions();
  await loadSessionDetail(session.session_id);
  return session;
}

async function ensureSession() {
  if (state.currentSessionId) {
    return state.currentSessionId;
  }
  const session = await createSession();
  return session.session_id;
}

async function loadSessions() {
  const response = await apiFetch("/v1/chat/sessions");
  const body = await response.json();
  state.sessions = body.sessions || [];
  syncSessionTitleFromList();
  renderSessions();
}

async function loadSessionDetail(sessionId) {
  const path = `/v1/chat/sessions/${sessionId}`;
  const response = await apiFetch(path);
  const detail = await response.json();
  state.currentSessionId = detail.session_id;
  els.sessionTitle.textContent = detail.title || "새 채팅";
  renderSessions();
  renderMessages(detail.messages || []);
}

function syncSessionTitleFromList() {
  if (!state.currentSessionId) {
    return;
  }
  const current = state.sessions.find((session) => session.session_id === state.currentSessionId);
  if (current) {
    els.sessionTitle.textContent = current.title || "새 채팅";
  }
}

/* ── Rendering ── */

function renderSessions() {
  els.sessionList.replaceChildren();
  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-button";
    empty.textContent = "저장된 채팅 없음";
    els.sessionList.append(empty);
    return;
  }

  for (const session of state.sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-button";
    button.classList.toggle("active", session.session_id === state.currentSessionId);
    button.textContent = session.title || "새 채팅";
    button.title = session.title || session.session_id;
    button.addEventListener("click", () => {
      loadSessionDetail(session.session_id).catch((error) => {
        setStatus(formatError(error), "error");
      });
    });
    els.sessionList.append(button);
  }
}

function renderMessages(messages) {
  els.messages.replaceChildren();
  if (!messages.length) {
    renderEmptyState();
    return;
  }
  for (const message of messages) {
    appendMessage(message.role, message.content);
  }
  scrollToBottom();
}

function renderEmptyState() {
  const wrapper = document.createElement("div");
  wrapper.className = "empty-state";
  const h1 = document.createElement("h1");
  h1.textContent = "무엇을 도와드릴까요?";
  wrapper.append(h1);
  els.messages.append(wrapper);
}

/* ── Math Protection ── */

function protectMath(text) {
  const blocks = [];
  const ph = (i) => `%%MATH_${i}%%`;

  // Display math: $$...$$ (multiline)
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (m, c) => {
    blocks.push({ content: c.trim(), display: true });
    return ph(blocks.length - 1);
  });
  // Display math: \[...\]
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (m, c) => {
    blocks.push({ content: c.trim(), display: true });
    return ph(blocks.length - 1);
  });
  // Inline math: \(...\)
  text = text.replace(/\\\((.+?)\\\)/g, (m, c) => {
    blocks.push({ content: c.trim(), display: false });
    return ph(blocks.length - 1);
  });
  // Inline math: $...$ (single line)
  text = text.replace(/\$([^\$\n]+?)\$/g, (m, c) => {
    blocks.push({ content: c.trim(), display: false });
    return ph(blocks.length - 1);
  });

  return { processed: text, blocks };
}

function restoreMathWithKatex(html, blocks) {
  return html.replace(/%%MATH_(\d+)%%/g, (_, idx) => {
    const block = blocks[parseInt(idx)];
    if (typeof katex !== "undefined") {
      try {
        return katex.renderToString(block.content, {
          displayMode: block.display,
          throwOnError: false,
        });
      } catch {
        return block.content;
      }
    }
    return block.content;
  });
}

/* ── Markdown ── */

function renderMarkdown(el, text) {
  if (!text || !text.trim()) {
    el.innerHTML = "";
    el.dataset.rawText = text || "";
    return;
  }
  if (typeof marked !== "undefined" && marked.parse) {
    const { processed, blocks } = protectMath(text);
    let html = marked.parse(processed, { breaks: true, gfm: true });
    if (blocks.length) {
      html = restoreMathWithKatex(html, blocks);
    }
    el.innerHTML = html;
  } else {
    el.textContent = text;
  }
  el.dataset.rawText = text;
}

let markdownRenderScheduled = false;
let markdownRenderRafId = 0;

function scheduleMarkdownRender(targetEl) {
  if (markdownRenderScheduled) return;
  markdownRenderScheduled = true;
  markdownRenderRafId = requestAnimationFrame(() => {
    renderMarkdown(targetEl, state.streamingText);
    scrollToBottom();
    markdownRenderScheduled = false;
    markdownRenderRafId = 0;
  });
}

function cancelPendingRender() {
  if (markdownRenderRafId) {
    cancelAnimationFrame(markdownRenderRafId);
    markdownRenderRafId = 0;
    markdownRenderScheduled = false;
  }
}

/* ── Typing Indicator ── */

function showTypingIndicator(targetEl) {
  const indicator = document.createElement("div");
  indicator.className = "typing-indicator";
  indicator.innerHTML = "<span></span><span></span><span></span>";
  targetEl.appendChild(indicator);
}

function hideTypingIndicator(targetEl) {
  const indicator = targetEl.querySelector(".typing-indicator");
  if (indicator) indicator.remove();
}

/* ── Copy Button ── */

function createCopyButton(messageTextEl) {
  const actions = document.createElement("div");
  actions.className = "message-actions";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "copy-button";
  btn.setAttribute("aria-label", "복사");
  btn.innerHTML = COPY_ICON;

  btn.addEventListener("click", () => {
    const rawText = messageTextEl.dataset.rawText || messageTextEl.textContent;
    navigator.clipboard.writeText(rawText).then(() => {
      btn.classList.add("copied");
      btn.innerHTML = CHECK_ICON;
      setTimeout(() => {
        btn.classList.remove("copied");
        btn.innerHTML = COPY_ICON;
      }, 2000);
    });
  });

  actions.append(btn);
  return actions;
}

/* ── Messages ── */

function appendMessage(role, content, files = []) {
  removeEmptyState();
  const outer = document.createElement("article");
  outer.className = `message ${role}`;

  const inner = document.createElement("div");
  inner.className = "message-inner";

  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "AI";
    inner.append(avatar);
  }

  const contentEl = document.createElement("div");
  contentEl.className = "message-content";

  if (files.length) {
    const filesEl = document.createElement("div");
    filesEl.className = "message-files";
    for (const file of files) {
      filesEl.append(createFileCard(file, "message"));
    }
    contentEl.append(filesEl);
  }

  const textEl = document.createElement("div");
  textEl.className = "message-text";

  if (role === "assistant" && content) {
    renderMarkdown(textEl, content);
  } else {
    textEl.textContent = content;
  }

  contentEl.append(textEl);

  if (role === "assistant") {
    contentEl.append(createCopyButton(textEl));
  }

  inner.append(contentEl);
  outer.append(inner);
  els.messages.append(outer);
  scrollToBottom();
  return textEl;
}

function createFileCard(file, variant) {
  const card = document.createElement("div");
  card.className = `file-card ${variant} ${fileKindClass(file.content_type || file.type || "", file.filename || file.name || "")}`;

  const icon = document.createElement("span");
  icon.className = "file-card-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "▤";

  const meta = document.createElement("span");
  meta.className = "file-card-meta";

  const name = document.createElement("span");
  name.className = "file-card-name";
  name.textContent = file.filename || file.name || "첨부 파일";
  name.title = name.textContent;

  const type = document.createElement("span");
  type.className = "file-card-type";
  type.textContent = fileKindLabel(file.content_type || file.type || "", file.filename || file.name || "");

  meta.append(name, type);
  card.append(icon, meta);
  return card;
}

function fileKindLabel(contentType, filename) {
  const normalized = `${contentType} ${filename}`.toLowerCase();
  if (normalized.includes("pdf")) {
    return "PDF";
  }
  if (
    normalized.includes("spreadsheetml") ||
    normalized.endsWith(".xlsx") ||
    normalized.endsWith(".xls") ||
    normalized.endsWith(".csv")
  ) {
    return "스프레드시트";
  }
  if (
    normalized.includes("wordprocessingml") ||
    normalized.includes("presentationml") ||
    normalized.endsWith(".docx") ||
    normalized.endsWith(".doc") ||
    normalized.endsWith(".pptx") ||
    normalized.endsWith(".ppt")
  ) {
    return "문서";
  }
  if (normalized.startsWith("image/")) {
    return "이미지";
  }
  if (normalized.startsWith("text/") || normalized.includes("json") || normalized.includes("xml")) {
    return "텍스트";
  }
  return "파일";
}

function fileKindClass(contentType, filename) {
  const normalized = `${contentType} ${filename}`.toLowerCase();
  if (normalized.includes("pdf") || normalized.endsWith(".pdf")) {
    return "file-kind-pdf";
  }
  if (
    normalized.includes("spreadsheetml") ||
    normalized.endsWith(".xlsx") ||
    normalized.endsWith(".xls") ||
    normalized.endsWith(".csv")
  ) {
    return "file-kind-sheet";
  }
  return "file-kind-doc";
}

function removeEmptyState() {
  const empty = els.messages.querySelector(".empty-state");
  if (empty) {
    empty.remove();
  }
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function autoResizeComposer() {
  els.messageInput.style.height = "auto";
  els.messageInput.style.height = `${Math.min(els.messageInput.scrollHeight, 190)}px`;
}

/* ── File Upload ── */

async function uploadSelectedFiles(files, sessionId) {
  const uploaded = [];
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    form.append("purpose", "chat_attachment");
    form.append("session_id", sessionId);

    const response = await apiFetch("/v1/files/upload", {
      method: "POST",
      body: form,
    });
    const body = await response.json();
    uploaded.push(body);
  }
  return uploaded;
}

function renderAttachedFiles() {
  els.attachedFiles.replaceChildren();
  for (const item of state.attachedFiles) {
    const chip = document.createElement("div");
    chip.className = "attached-file";

    chip.append(createFileCard(item.file, "composer"));

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "×";
    button.setAttribute("aria-label", "첨부 파일 제거");
    button.addEventListener("click", () => {
      state.attachedFiles = state.attachedFiles.filter((fileItem) => fileItem !== item);
      renderAttachedFiles();
    });

    chip.append(button);
    els.attachedFiles.append(chip);
  }
}

/* ── Send Message ── */

async function sendMessage() {
  const message = els.messageInput.value.trim();
  if (!message && !state.attachedFiles.length) {
    return;
  }

  setBusy(true);
  setStatus("응답 대기 중");
  state.streamingText = "";
  const filesForMessage = [...state.attachedFiles];
  let assistantContent = null;
  state.attachedFiles = [];
  renderAttachedFiles();

  try {
    const sessionId = await ensureSession();
    const uploadedFiles = filesForMessage.length
      ? await uploadSelectedFiles(
          filesForMessage.map((item) => item.file),
          sessionId,
        )
      : [];
    const fileIds = uploadedFiles.map((file) => file.id);

    appendMessage("user", message || "첨부 파일", uploadedFiles);
    els.messageInput.value = "";
    autoResizeComposer();

    assistantContent = appendMessage("assistant", "");
    showTypingIndicator(assistantContent);

    await streamAssistantResponse(
      sessionId,
      message || "첨부 파일을 분석해줘.",
      fileIds,
      assistantContent,
    );
    setStatus("완료", "ok");
    await loadSessions();
  } catch (error) {
    setStatus(formatError(error), "error");
    if (assistantContent) {
      hideTypingIndicator(assistantContent);
      assistantContent.textContent = `오류: ${formatError(error)}`;
      assistantContent.dataset.rawText = "";
    } else {
      appendMessage("assistant", `오류: ${formatError(error)}`);
    }
    state.attachedFiles = [...filesForMessage, ...state.attachedFiles];
    renderAttachedFiles();
  } finally {
    state.streamingText = "";
    setBusy(false);
    els.messageInput.focus();
  }
}

/* ── SSE Streaming ── */

async function streamAssistantResponse(sessionId, message, fileIds, targetEl) {
  const path = `/v1/chat/sessions/${sessionId}/messages/stream`;
  const response = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, file_ids: fileIds }),
  });

  if (!response.body) {
    throw new Error("브라우저가 스트리밍 응답을 지원하지 않습니다.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const result = consumeSseBuffer(buffer, targetEl);
    buffer = result.remaining;
  }

  buffer += decoder.decode();
  consumeSseBuffer(buffer, targetEl);
}

function consumeSseBuffer(buffer, targetEl) {
  const chunks = buffer.split("\n\n");
  const remaining = chunks.pop() || "";
  for (const chunk of chunks) {
    handleSseEvent(chunk, targetEl);
  }
  return { remaining };
}

function handleSseEvent(rawEvent, targetEl) {
  const lines = rawEvent.split("\n");
  let eventName = "message";
  const dataLines = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }

  if (!dataLines.length) {
    return;
  }

  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    data = { delta: dataLines.join("\n") };
  }

  if (eventName === "metadata") {
    return;
  }

  if (eventName === "token") {
    hideTypingIndicator(targetEl);
    state.streamingText += data.delta || "";
    scheduleMarkdownRender(targetEl);
    return;
  }

  if (eventName === "done") {
    hideTypingIndicator(targetEl);
    cancelPendingRender();
    const finalText = data.full_response || state.streamingText;
    renderMarkdown(targetEl, finalText);
    state.streamingText = "";
    scrollToBottom();
    return;
  }

  if (eventName === "error") {
    hideTypingIndicator(targetEl);
    throw new Error(data.message || "SSE stream error");
  }
}

/* ── Event Binding ── */

function bindEvents() {
  els.healthCheckButton.addEventListener("click", healthCheck);

  els.refreshSessionsButton.addEventListener("click", () => {
    loadSessions()
      .then(() => setStatus("세션 목록 갱신", "ok"))
      .catch((error) => setStatus(formatError(error), "error"));
  });

  els.newChatButton.addEventListener("click", () => {
    createSession()
      .then(() => setStatus("새 채팅 생성", "ok"))
      .catch((error) => setStatus(formatError(error), "error"));
  });

  els.fileInput.addEventListener("change", () => {
    const selected = [...els.fileInput.files].map((file) => ({ file, name: file.name }));
    state.attachedFiles.push(...selected);
    els.fileInput.value = "";
    renderAttachedFiles();
  });

  els.sendButton.addEventListener("click", () => {
    sendMessage();
  });

  els.messageInput.addEventListener("input", autoResizeComposer);

  let justFinishedComposing = false;
  els.messageInput.addEventListener("compositionstart", () => {
    justFinishedComposing = false;
  });
  els.messageInput.addEventListener("compositionend", () => {
    justFinishedComposing = true;
    setTimeout(() => { justFinishedComposing = false; }, 0);
  });
  els.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      if (event.isComposing || justFinishedComposing) {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      sendMessage();
    }
  });
}

/* ── Init ── */

bindEvents();
healthCheck();
loadSessions().catch(() => {});

"use strict";

// Legacy single-file UI bundle. The active UI loads ./js/main.js from index.html.

const COPY_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
const CHECK_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

/* ── State ── */

const state = {
  currentView: "chat",
  currentSessionId: null,
  sessions: [],
  attachedFiles: [],
  sources: [],
  files: [],
  filesCursor: null,
  filesHasMore: false,
  isSending: false,
  isSourceBusy: false,
  streamingText: "",
};

/* ── DOM Elements ── */

const els = {
  userIdInput: document.querySelector("#userIdInput"),
  teamIdInput: document.querySelector("#teamIdInput"),
  healthCheckButton: document.querySelector("#healthCheckButton"),
  newChatButton: document.querySelector("#newChatButton"),
  refreshSessionsButton: document.querySelector("#refreshSessionsButton"),
  sessionList: document.querySelector("#sessionList"),
  viewSourcesButton: document.querySelector("#viewSourcesButton"),
  chatView: document.querySelector("#chatView"),
  connectionStatus: document.querySelector("#connectionStatus"),
  sessionTitle: document.querySelector("#sessionTitle"),
  messages: document.querySelector("#messages"),
  attachedFiles: document.querySelector("#attachedFiles"),
  fileInput: document.querySelector("#fileInput"),
  messageInput: document.querySelector("#messageInput"),
  sendButton: document.querySelector("#sendButton"),
  sourcesView: document.querySelector("#sourcesView"),
  closeSourcesBtn: document.querySelector("#closeSourcesBtn"),
  sourceUploadTrigger: document.querySelector("#sourceUploadTrigger"),
  sourceFileInput: document.querySelector("#sourceFileInput2"),
  sourceStatusBar: document.querySelector("#sourceStatusBar"),
  sourceStatusText: document.querySelector("#sourceStatusText"),
  sourceCount: document.querySelector("#sourceCount"),
  sourceList: document.querySelector("#sourceList2"),
  refreshSourcesBtn: document.querySelector("#refreshSourcesBtn"),
  filesList: document.querySelector("#filesList"),
  loadMoreFilesBtn: document.querySelector("#loadMoreFilesBtn"),
  docViewerModal: document.querySelector("#docViewerModal"),
  docViewerTitle: document.querySelector("#docViewerTitle"),
  docViewerBody: document.querySelector("#docViewerBody"),
  docViewerClose: document.querySelector("#docViewerClose"),
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

function buildLinkUrl(path, query = "") {
  const params = new URLSearchParams(query);
  params.set("test_user_id", String(getUserId()));
  const teamId = getTeamId();
  if (teamId !== null) {
    params.set("test_team_id", String(teamId));
  }
  return buildUrl(path, params.toString());
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

function setSourceBusy(isBusy) {
  state.isSourceBusy = isBusy;
  if(els.sourceUploadTrigger) {
    els.sourceUploadTrigger.disabled = isBusy;
  }
}

function setSourceStatus(message, type = "") {
  els.sourceStatusBar.hidden = !message;
  els.sourceStatusText.textContent = message;
  els.sourceStatusBar.classList.toggle("ok", type === "ok");
  els.sourceStatusBar.classList.toggle("error", type === "error");
}

function formatError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function formatFileSize(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

/* ── View Switching ── */

function switchView(view) {
  state.currentView = view;
  if (view === "chat") {
    // Only toggling sources panel visibility now
    els.sourcesView.hidden = true;
    els.viewSourcesButton.classList.remove("active");
  } else {
    els.sourcesView.hidden = false;
    els.viewSourcesButton.classList.add("active");
    loadSources().catch(() => {});
    loadFiles(true).catch(() => {});
  }
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

/* ── Health / Ready ── */

async function healthCheck() {
  try {
    const response = await fetch(buildUrl("/health"));
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    const body = await response.json();
    let readyLabel = "";
    try {
      const readyRes = await fetch(buildUrl("/ready"));
      readyLabel = readyRes.ok ? " · ready" : " · not ready";
    } catch {
      readyLabel = "";
    }
    setStatus(`${body.status || "ok"} · ${body.version || "unknown"}${readyLabel}`, "ok");
  } catch (error) {
    setStatus(formatError(error), "error");
  }
}

/* ── Sessions ── */

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

/* ── RAG Sources ── */

async function loadSources() {
  const response = await apiFetch("/v1/sources");
  const body = await response.json();
  state.sources = body.sources || [];
  renderSourcesList();
  return state.sources;
}

async function addSelectedSource() {
  const file = els.sourceFileInput.files[0];
  if (!file) {
    setSourceStatus("소스 파일을 선택하세요.", "error");
    return;
  }
  if (getTeamId() === null) {
    setSourceStatus("RAG 소스는 Team ID가 필요합니다.", "error");
    return;
  }

  setSourceBusy(true);
  setSourceStatus("소스 파일 업로드 중...");
  try {
    const uploaded = await uploadRagSourceFile(file);
    setSourceStatus("소스 등록 중...");
    const source = await createDocumentSource(uploaded);
    setSourceStatus("인덱싱 작업 생성 중...");
    const job = await createIngestionJob(source.source_id);
    setSourceStatus("인덱싱 중. worker가 실행 중이어야 합니다.");
    const completed = await waitForIngestionJob(job.job_id);
    await loadSources();
    await loadFiles(true);
    if (completed.status === "succeeded") {
      setSourceStatus(
        `인덱싱 완료: ${uploaded.filename} · ${completed.indexed_object_count}개 chunk`,
        "ok",
      );
      els.sourceFileInput.value = "";
    } else {
      setSourceStatus(completed.failure_reason || "인덱싱 실패", "error");
    }
  } catch (error) {
    setSourceStatus(formatError(error), "error");
  } finally {
    setSourceBusy(false);
  }
}

async function uploadRagSourceFile(file) {
  const form = new FormData();
  form.append("file", file);
  form.append("purpose", "rag_source");

  const response = await apiFetch("/v1/files/upload", {
    method: "POST",
    body: form,
  });
  return response.json();
}

async function createDocumentSource(file) {
  const response = await apiFetch("/v1/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: "document",
      name: file.filename,
      file_id: file.id,
    }),
  });
  return response.json();
}

async function createIngestionJob(sourceId) {
  const response = await apiFetch("/v1/ingestion-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, mode: "full" }),
  });
  return response.json();
}

async function waitForIngestionJob(jobId) {
  const startedAt = Date.now();
  const timeoutMs = 180000;
  while (Date.now() - startedAt < timeoutMs) {
    const response = await apiFetch(`/v1/ingestion-jobs/${jobId}`);
    const job = await response.json();
    if (job.status === "succeeded" || job.status === "failed") {
      return job;
    }
    await sleep(2000);
  }
  throw new Error("인덱싱 대기 시간이 초과되었습니다. worker 상태를 확인하세요.");
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function deleteSource(sourceId) {
  setSourceBusy(true);
  setSourceStatus("소스 삭제 중...");
  try {
    await apiFetch(`/v1/sources/${sourceId}`, { method: "DELETE" });
    await loadSources();
    setSourceStatus("소스를 삭제했습니다.", "ok");
  } catch (error) {
    setSourceStatus(formatError(error), "error");
  } finally {
    setSourceBusy(false);
  }
}

/* ── Files API ── */

async function loadFiles(reset = true) {
  if (reset) {
    state.files = [];
    state.filesCursor = null;
    state.filesHasMore = false;
  }
  const params = new URLSearchParams({ limit: "20" });
  if (state.filesCursor) {
    params.set("cursor", state.filesCursor);
  }
  try {
    const response = await apiFetch("/v1/files", { query: params.toString() });
    const body = await response.json();
    const newFiles = body.files || [];
    state.files = reset ? newFiles : [...state.files, ...newFiles];
    state.filesCursor = body.next_cursor || null;
    state.filesHasMore = body.has_more || false;
    renderFilesList();
  } catch (error) {
    console.error("파일 목록 조회 실패:", error);
  }
}

/* ── Rendering — Sessions ── */

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
      if (state.currentView !== "chat") {
        switchView("chat");
      }
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
    appendMessage(message.role, message.content, [], message.citations || []);
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

/* ── Rendering — Sources View ── */

function renderSourcesList() {
  els.sourceList.replaceChildren();
  els.sourceCount.textContent = state.sources.length;

  if (!state.sources.length) {
    const empty = document.createElement("div");
    empty.className = "src-empty";
    empty.textContent = "등록된 소스가 없습니다. 파일을 업로드하여 소스를 추가하세요.";
    els.sourceList.append(empty);
    return;
  }

  for (const source of state.sources) {
    els.sourceList.append(createSourceCard(source));
  }
}

function createSourceCard(source) {
  const card = document.createElement("div");
  card.className = "src-card";

  const info = document.createElement("div");
  info.className = "src-card-info";

  const icon = document.createElement("div");
  icon.className = "src-card-icon";
  icon.textContent = source.source_type === "repository" ? "📦" : "📄";

  const metaBox = document.createElement("div");
  metaBox.className = "src-card-meta";

  const name = document.createElement("p");
  name.className = "src-card-name";
  name.textContent = source.name || source.source_id;
  name.title = name.textContent;

  const details = document.createElement("p");
  details.className = "src-card-details";
  const statusLabel = { registered: "⬜ 등록됨", indexing: "⏳ 인덱싱", ready: "✅ 사용", error: "❌ 오류" };
  details.textContent = `${statusLabel[source.status] || source.status} · ${source.chunk_count || 0} chunks`;

  metaBox.append(name, details);
  info.append(icon, metaBox);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "src-card-delete";
  deleteBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`;
  deleteBtn.title = "삭제";
  deleteBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    deleteSource(source.source_id);
  });

  card.append(info, deleteBtn);
  return card;
}

/* ── Rendering — Files List ── */

function renderFilesList() {
  els.filesList.replaceChildren();

  if (!state.files.length) {
    const empty = document.createElement("div");
    empty.className = "files-empty";
    empty.textContent = "업로드된 파일이 없습니다.";
    els.filesList.append(empty);
    els.loadMoreFilesBtn.hidden = true;
    return;
  }

  for (const file of state.files) {
    els.filesList.append(createFileListItem(file));
  }
  els.loadMoreFilesBtn.hidden = !state.filesHasMore;
}

function createFileListItem(file) {
  const item = document.createElement("div");
  item.className = "src-card"; // using the same styling as source card

  const info = document.createElement("div");
  info.className = "src-card-info";

  const icon = document.createElement("div");
  icon.className = "src-card-icon";
  icon.textContent = "▤";

  const metaBox = document.createElement("div");
  metaBox.className = "src-card-meta";

  const name = document.createElement("p");
  name.className = "src-card-name";
  name.textContent = file.filename;
  name.title = file.filename;

  const details = document.createElement("p");
  details.className = "src-card-details";
  const size = formatFileSize(file.file_size);
  details.textContent = `${size} · ${new Date(file.created_at).toLocaleDateString("ko-KR")}`;

  metaBox.append(name, details);
  info.append(icon, metaBox);

  const downloadLink = document.createElement("a");
  downloadLink.href = buildLinkUrl(`/v1/files/${file.id}/download`);
  downloadLink.target = "_blank";
  downloadLink.rel = "noreferrer";
  downloadLink.className = "src-card-delete"; // reuse button style
  downloadLink.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
  downloadLink.title = "다운로드";

  item.append(info, downloadLink);
  return item;
}

/* ── Math Protection ── */

function protectMath(text) {
  const blocks = [];
  const ph = (i) => `%%MATH_${i}%%`;

  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (m, c) => {
    blocks.push({ content: c.trim(), display: true });
    return ph(blocks.length - 1);
  });
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (m, c) => {
    blocks.push({ content: c.trim(), display: true });
    return ph(blocks.length - 1);
  });
  text = text.replace(/\\\((.+?)\\\)/g, (m, c) => {
    blocks.push({ content: c.trim(), display: false });
    return ph(blocks.length - 1);
  });
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

function appendMessage(role, content, files = [], citations = []) {
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
    if (citations.length) {
      processInlineCitations(textEl, citations);
    }
  } else {
    textEl.textContent = content;
  }

  contentEl.append(textEl);

  if (role === "assistant") {
    renderCitations(contentEl, citations);
    contentEl.append(createCopyButton(textEl));
  }

  inner.append(contentEl);
  outer.append(inner);
  els.messages.append(outer);
  scrollToBottom();
  return textEl;
}

function renderCitations(contentEl, citations = []) {
  const existing = contentEl.querySelector(".citation-list");
  if (existing) {
    existing.remove();
  }
  if (!citations.length) {
    return;
  }

  const list = document.createElement("div");
  list.className = "citation-list";

  for (const citation of citations) {
    const link = document.createElement("a");
    link.className = "citation-link";
    link.dataset.index = citation.index;

    const isExternal = citation.url && !citation.url.startsWith("/v1/");

    if (isExternal) {
      link.href = citation.url;
      link.target = "_blank";
      link.rel = "noreferrer";
    } else {
      link.href = "#";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        showDocumentViewer(citation);
      });
    }

    const iconSpan = document.createElement("span");
    iconSpan.className = "citation-icon";
    iconSpan.textContent = citation.source_type === "repository" ? "📦" : "📄";

    const label = document.createElement("span");
    label.className = "citation-label";
    label.textContent = `[${citation.index}]`;

    const text = document.createElement("span");
    text.className = "citation-title";
    const locator = citation.line_start
      ? `L${citation.line_start}${citation.line_end ? `-L${citation.line_end}` : ""}`
      : `chunk ${citation.chunk_index ?? 0}`;
    text.textContent = `${citation.title || citation.path || "source"} · ${locator}`;

    link.append(iconSpan, label, text);
    list.append(link);
  }

  contentEl.append(list);
}

function citationUrl(url) {
  if (!url) {
    return "#";
  }
  if (url.startsWith("/v1/")) {
    return buildLinkUrl(url);
  }
  return url;
}

/* ── Inline Citation Processing ── */

function processInlineCitations(el, citations) {
  if (!citations.length) return;

  const citationByIndex = new Map();
  for (const citation of citations) {
    const index = Number.parseInt(citation.index, 10);
    if (Number.isInteger(index) && index > 0) {
      citationByIndex.set(index, citation);
    }
  }
  if (!citationByIndex.size) return;

  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (/\[\d+\]/.test(node.textContent)) {
      textNodes.push(node);
    }
  }

  for (const textNode of textNodes) {
    const parts = textNode.textContent.split(/(\[\d+\])/g);
    if (parts.length <= 1) continue;

    const fragment = document.createDocumentFragment();
    for (const part of parts) {
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const index = Number.parseInt(match[1], 10);
        const citation = citationByIndex.get(index);
        if (!citation) {
          fragment.appendChild(document.createTextNode(part));
          continue;
        }
        const badge = document.createElement("span");
        badge.className = "inline-citation";
        badge.textContent = `[${index}]`;
        badge.dataset.index = String(index);
        badge.title = citation.title || citation.path || `출처 ${index}`;
        badge.addEventListener("click", () => {
          const citationEl = el
            .closest(".message-content")
            ?.querySelector(`.citation-link[data-index="${index}"]`);
          if (citationEl) {
            citationEl.classList.add("highlight");
            citationEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
            setTimeout(() => citationEl.classList.remove("highlight"), 2000);
          }
          const isExternal = citation.url && !citation.url.startsWith("/v1/");
          if (!isExternal) {
            showDocumentViewer(citation);
          }
        });
        fragment.appendChild(badge);
      } else if (part) {
        fragment.appendChild(document.createTextNode(part));
      }
    }
    textNode.parentNode.replaceChild(fragment, textNode);
  }
}

/* ── Document Viewer Modal ── */

function showDocumentViewer(citation) {
  if (!citation) return;

  const isExternal = citation.url && !citation.url.startsWith("/v1/");
  if (isExternal) {
    window.open(citation.url, "_blank", "noreferrer");
    return;
  }

  els.docViewerTitle.textContent = citation.title || citation.path || "문서 보기";
  els.docViewerBody.replaceChildren();

  const url = citationUrl(citation.url);

  if (url && url !== "#") {
    const filename = (citation.title || citation.path || "").toLowerCase();

    if (filename.endsWith(".pdf")) {
      const iframe = document.createElement("iframe");
      iframe.src = url;
      iframe.className = "doc-viewer-iframe";
      iframe.setAttribute("loading", "lazy");
      els.docViewerBody.append(iframe);
    } else {
      const loading = document.createElement("div");
      loading.className = "doc-viewer-loading";
      loading.textContent = "문서를 불러오는 중...";
      els.docViewerBody.append(loading);

      fetch(url)
        .then((res) => {
          if (res.redirected) {
            return fetch(res.url).then((r) => {
              if (!r.ok) throw new Error(`${r.status}`);
              return r.text();
            });
          }
          if (!res.ok) throw new Error(`${res.status}`);
          return res.text();
        })
        .then((text) => {
          els.docViewerBody.replaceChildren();
          const pre = document.createElement("pre");
          pre.className = "doc-viewer-text";
          pre.textContent = text;
          els.docViewerBody.append(pre);
        })
        .catch(() => {
          els.docViewerBody.replaceChildren();
          const fallback = document.createElement("div");
          fallback.className = "doc-viewer-fallback";
          const p = document.createElement("p");
          p.textContent = "문서를 표시할 수 없습니다.";
          const a = document.createElement("a");
          a.href = url;
          a.target = "_blank";
          a.rel = "noreferrer";
          a.textContent = "새 탭에서 열기 ↗";
          fallback.append(p, a);
          els.docViewerBody.append(fallback);
        });
    }
  } else {
    const noContent = document.createElement("div");
    noContent.className = "doc-viewer-fallback";
    noContent.textContent = "문서 URL을 사용할 수 없습니다.";
    els.docViewerBody.append(noContent);
  }

  els.docViewerModal.hidden = false;
  document.body.classList.add("modal-open");
}

function hideDocumentViewer() {
  els.docViewerModal.hidden = true;
  document.body.classList.remove("modal-open");
  els.docViewerBody.replaceChildren();
}

/* ── File Cards ── */

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

/* ── Helpers ── */

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

/* ── File Upload (chat attachments) ── */

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
    const citations = data.citations || [];
    renderMarkdown(targetEl, finalText);
    if (citations.length) {
      processInlineCitations(targetEl, citations);
    }
    renderCitations(targetEl.parentElement, citations);
    state.streamingText = "";
    scrollToBottom();
    return;
  }

  if (eventName === "error") {
    hideTypingIndicator(targetEl);
    throw new Error(data.message || "SSE stream error");
  }
}

/* ── Source Upload Binding ── */

function setupSourceUpload() {
  const triggerBtn = els.sourceUploadTrigger;
  
  if (triggerBtn) {
    triggerBtn.addEventListener("click", () => {
      if (!state.isSourceBusy) {
        els.sourceFileInput.click();
      }
    });
  }

  els.sourceFileInput.addEventListener("change", () => {
    if (els.sourceFileInput.files.length) {
      addSelectedSource();
    }
  });
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
    if (state.currentView !== "chat") {
      switchView("chat");
    }
    createSession()
      .then(() => setStatus("새 채팅 생성", "ok"))
      .catch((error) => setStatus(formatError(error), "error"));
  });

  // View switching
  els.viewSourcesButton.addEventListener("click", () => {
    switchView(state.currentView === "sources" ? "chat" : "sources");
  });

  if (els.closeSourcesBtn) {
    els.closeSourcesBtn.addEventListener("click", () => {
      switchView("chat");
    });
  }

  // Sources view
  els.refreshSourcesBtn.addEventListener("click", () => {
    loadSources()
      .then(() => setSourceStatus("소스 목록 갱신", "ok"))
      .catch((error) => setSourceStatus(formatError(error), "error"));
  });

  setupSourceUpload();

  // Files pagination
  els.loadMoreFilesBtn.addEventListener("click", () => {
    loadFiles(false).catch(console.error);
  });

  // Document viewer modal
  els.docViewerClose.addEventListener("click", hideDocumentViewer);
  const backdrop = els.docViewerModal.querySelector(".modal-backdrop");
  if (backdrop) {
    backdrop.addEventListener("click", hideDocumentViewer);
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.docViewerModal.hidden) {
      hideDocumentViewer();
    }
  });

  // Chat attachments
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

  // IME composition handling
  let justFinishedComposing = false;
  els.messageInput.addEventListener("compositionstart", () => {
    justFinishedComposing = false;
  });
  els.messageInput.addEventListener("compositionend", () => {
    justFinishedComposing = true;
    setTimeout(() => {
      justFinishedComposing = false;
    }, 0);
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

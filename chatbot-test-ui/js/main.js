"use strict";

import { state } from "./state.js";
import { healthCheck } from "./api.js";
import { formatError } from "./utils.js";
import { initModal, hideDocumentViewer } from "./modal.js";
import {
  initSessions,
  createSession,
  loadSessions,
  loadSessionDetail,
  setOnSelectSession,
} from "./sessions.js";
import {
  initSources,
  loadSources,
} from "./sources.js";
import { initFiles, loadFiles } from "./files.js";
import {
  initChat,
  sendMessage,
  autoResizeComposer,
  renderAttachedFiles,
  renderMessages,
} from "./chat.js";

/* ── DOM Element References ── */

const $ = (sel) => document.querySelector(sel);

const els = {
  // Sidebar
  newChatBtn: $("#newChatBtn"),
  refreshSessionsBtn: $("#refreshSessionsBtn"),
  healthCheckBtn: $("#healthCheckBtn"),
  sessionList: $("#sessionList"),
  sessionTitle: $("#sessionTitle"),
  viewSourcesBtn: $("#viewSourcesBtn"),

  // Settings
  userIdInput: $("#userIdInput"),
  teamIdInput: $("#teamIdInput"),

  // Sources panel
  sourcesPanel: $("#sourcesPanel"),
  closeSourcesBtn: $("#closeSourcesBtn"),
  refreshSourcesBtn: $("#refreshSourcesBtn"),
  sourceUploadBtn: $("#sourceUploadBtn"),
  sourceFileInput: $("#sourceFileInput"),
  sourceStatusBar: $("#sourceStatusBar"),
  sourceStatusText: $("#sourceStatusText"),
  sourceCount: $("#sourceCount"),
  sourceList: $("#sourceList"),
  filesList: $("#filesList"),
  loadMoreFilesBtn: $("#loadMoreFilesBtn"),
  repoSourceToggle: $("#repoSourceToggle"),
  repoSourceForm: $("#repoSourceForm"),
  repoUrlInput: $("#repoUrlInput"),
  repoBranchInput: $("#repoBranchInput"),

  // Chat
  chatView: $("#chatView"),
  connectionStatus: $("#connectionStatus"),
  messages: $("#messages"),
  attachedFiles: $("#attachedFiles"),
  fileInput: $("#fileInput"),
  messageInput: $("#messageInput"),
  sendButton: $("#sendButton"),

  // Modal
  docViewerModal: $("#docViewerModal"),
  docViewerTitle: $("#docViewerTitle"),
  docViewerBody: $("#docViewerBody"),
  docViewerClose: $("#docViewerClose"),
};

/* ── Status Display ── */

function setStatus(message, type = "") {
  if (!els.connectionStatus) return;
  els.connectionStatus.textContent = message;
  els.connectionStatus.className = "status-pill";
  if (type === "ok") els.connectionStatus.classList.add("ok");
  if (type === "error") els.connectionStatus.classList.add("error");
}

/* ── View Switching ── */

function switchView(view) {
  state.currentView = view;
  if (view === "sources") {
    if (els.sourcesPanel) els.sourcesPanel.hidden = false;
    els.viewSourcesBtn?.classList.add("active");
    loadSources().catch(() => {});
    loadFiles(true).catch(() => {});
  } else {
    if (els.sourcesPanel) els.sourcesPanel.hidden = true;
    els.viewSourcesBtn?.classList.remove("active");
  }
}

/* ── Initialize Modules ── */

// Sessions
initSessions(els.sessionList, els.sessionTitle);
setOnSelectSession((sessionId) => {
  if (state.currentView !== "chat") switchView("chat");
  loadSessionDetail(sessionId, renderMessages).catch((err) =>
    setStatus(formatError(err), "error"),
  );
});

// Sources
initSources({
  sourceList: els.sourceList,
  sourceCount: els.sourceCount,
  sourceStatusBar: els.sourceStatusBar,
  sourceStatusText: els.sourceStatusText,
  sourceFileInput: els.sourceFileInput,
  sourceUploadBtn: els.sourceUploadBtn,
  repoSourceToggle: els.repoSourceToggle,
  repoSourceForm: els.repoSourceForm,
  repoUrlInput: els.repoUrlInput,
  repoBranchInput: els.repoBranchInput,
});

// Files
initFiles(els.filesList, els.loadMoreFilesBtn);

// Chat
initChat({
  messagesEl: els.messages,
  messageInput: els.messageInput,
  sendButton: els.sendButton,
  fileInput: els.fileInput,
  attachedFilesEl: els.attachedFiles,
  setStatus,
});

// Modal
if (els.docViewerModal) {
  initModal(els.docViewerModal, els.docViewerTitle, els.docViewerBody);
  els.docViewerClose?.addEventListener("click", hideDocumentViewer);
}

/* ── Event Binding ── */

// Health check
els.healthCheckBtn?.addEventListener("click", () => healthCheck(setStatus));

// Sessions
els.refreshSessionsBtn?.addEventListener("click", () => {
  loadSessions()
    .then(() => setStatus("세션 목록 갱신", "ok"))
    .catch((err) => setStatus(formatError(err), "error"));
});

els.newChatBtn?.addEventListener("click", () => {
  if (state.currentView !== "chat") switchView("chat");
  createSession()
    .then(() => {
      renderMessages([]);
      setStatus("새 채팅 생성", "ok");
    })
    .catch((err) => setStatus(formatError(err), "error"));
});

// Sources view
els.viewSourcesBtn?.addEventListener("click", () => {
  switchView(state.currentView === "sources" ? "chat" : "sources");
});

els.closeSourcesBtn?.addEventListener("click", () => switchView("chat"));

els.refreshSourcesBtn?.addEventListener("click", () => {
  loadSources().catch(console.warn);
  loadFiles(true).catch(console.warn);
});

// Chat attachments
els.fileInput?.addEventListener("change", () => {
  const selected = [...els.fileInput.files].map((file) => ({
    file,
    name: file.name,
  }));
  state.attachedFiles = [...state.attachedFiles, ...selected];
  els.fileInput.value = "";
  renderAttachedFiles();
});

els.sendButton?.addEventListener("click", sendMessage);

els.messageInput?.addEventListener("input", autoResizeComposer);

// IME composition handling (Korean input)
let justFinishedComposing = false;
els.messageInput?.addEventListener("compositionstart", () => {
  justFinishedComposing = false;
});
els.messageInput?.addEventListener("compositionend", () => {
  justFinishedComposing = true;
  setTimeout(() => {
    justFinishedComposing = false;
  }, 0);
});
els.messageInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    if (event.isComposing || justFinishedComposing) {
      event.preventDefault();
      return;
    }
    event.preventDefault();
    sendMessage();
  }
});

/* ── Startup ── */

healthCheck(setStatus);
loadSessions().catch(() => {});

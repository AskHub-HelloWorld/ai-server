"use strict";

import { state } from "./state.js";
import { apiFetch, buildLinkUrl } from "./api.js";
import { formatError, scrollToBottom, ICONS } from "./utils.js";
import {
  renderMarkdown,
  scheduleMarkdownRender,
  cancelPendingRender,
} from "./markdown.js";
import { showDocumentViewer } from "./modal.js";
import { ensureSession, loadSessions } from "./sessions.js";
import { uploadSelectedFiles, createFileCard } from "./files.js";

/* ── DOM references ── */
let _messagesEl, _messageInput, _sendButton, _fileInput, _attachedFilesEl;
let _setStatus;

export function initChat({
  messagesEl,
  messageInput,
  sendButton,
  fileInput,
  attachedFilesEl,
  setStatus,
}) {
  _messagesEl = messagesEl;
  _messageInput = messageInput;
  _sendButton = sendButton;
  _fileInput = fileInput;
  _attachedFilesEl = attachedFilesEl;
  _setStatus = setStatus;
}

/* ── Busy state ── */

function setBusy(isBusy) {
  state.isSending = isBusy;
  if (_sendButton) _sendButton.disabled = isBusy;
  if (_fileInput) _fileInput.disabled = isBusy;
  if (_messageInput) _messageInput.disabled = isBusy;
}

/* ── Auto-resize textarea ── */

export function autoResizeComposer() {
  if (!_messageInput) return;
  _messageInput.style.height = "auto";
  _messageInput.style.height = `${Math.min(_messageInput.scrollHeight, 190)}px`;
}

/* ── Attached files ── */

export function renderAttachedFiles() {
  if (!_attachedFilesEl) return;
  _attachedFilesEl.replaceChildren();

  for (const item of state.attachedFiles) {
    const chip = document.createElement("div");
    chip.className = "attached-file";
    chip.append(createFileCard(item.file, "composer"));

    const btn = document.createElement("button");
    btn.type = "button";
    btn.innerHTML = ICONS.close;
    btn.setAttribute("aria-label", "첨부 파일 제거");
    btn.addEventListener("click", () => {
      state.attachedFiles = state.attachedFiles.filter((f) => f !== item);
      renderAttachedFiles();
    });

    chip.append(btn);
    _attachedFilesEl.append(chip);
  }
}

/* ── Messages rendering ── */

export function renderMessages(messages) {
  if (!_messagesEl) return;
  _messagesEl.replaceChildren();
  if (!messages.length) {
    renderEmptyState();
    return;
  }
  for (const msg of messages) {
    appendMessage(msg.role, msg.content, [], msg.citations || [], {
      responseType: msg.response_type,
      status: msg.status,
      failureReason: msg.failure_reason,
    });
  }
  scrollToBottom(_messagesEl);
}

function renderEmptyState() {
  const wrapper = document.createElement("div");
  wrapper.className = "empty-state";
  const h1 = document.createElement("h1");
  h1.textContent = "무엇을 도와드릴까요?";
  const sub = document.createElement("p");
  sub.textContent = "AskHub AI에 질문하거나, 파일을 첨부하여 분석해 보세요.";
  wrapper.append(h1, sub);
  _messagesEl.append(wrapper);
}

function removeEmptyState() {
  const el = _messagesEl?.querySelector(".empty-state");
  if (el) el.remove();
}

/* ── Typing indicator ── */

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

/* ── Copy button ── */

function createCopyButton(messageTextEl) {
  const actions = document.createElement("div");
  actions.className = "message-actions";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "copy-button";
  btn.setAttribute("aria-label", "복사");
  btn.innerHTML = ICONS.copy;

  btn.addEventListener("click", () => {
    const rawText = messageTextEl.dataset.rawText || messageTextEl.textContent;
    navigator.clipboard.writeText(rawText).then(() => {
      btn.classList.add("copied");
      btn.innerHTML = ICONS.check;
      setTimeout(() => {
        btn.classList.remove("copied");
        btn.innerHTML = ICONS.copy;
      }, 2000);
    });
  });

  actions.append(btn);
  return actions;
}

/* ── Append message ── */

export function appendMessage(role, content, files = [], citations = [], options = {}) {
  removeEmptyState();
  const { answerable, status, failureReason } = options;

  const outer = document.createElement("article");
  outer.className = `message ${role}`;
  if (status === "failed") outer.classList.add("failed");

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

  if (status === "failed") {
    textEl.textContent = failureReason || content || "응답 생성에 실패했습니다.";
  } else if (role === "assistant" && content) {
    renderMarkdown(textEl, content);
    if (citations.length) {
      processInlineCitations(textEl, citations);
    }
  } else {
    textEl.textContent = content;
  }

  contentEl.append(textEl);

  if (role === "assistant") {
    if (options.responseType) {
      renderAnswerableBadge(textEl, options.responseType);
    }
    renderCitations(contentEl, citations);
    contentEl.append(createCopyButton(textEl));
  }

  inner.append(contentEl);
  outer.append(inner);
  _messagesEl.append(outer);
  scrollToBottom(_messagesEl);
  return textEl;
}

/* ── Answerable Badge ── */

function renderAnswerableBadge(targetEl, responseType) {
  const contentEl = targetEl.closest(".message-content");
  if (!contentEl || !responseType) return;

  const existing = contentEl.querySelector(".answerable-badge");
  if (existing) existing.remove();

  const badge = document.createElement("div");
  badge.className = "answerable-badge";

  if (responseType === "rag") {
    badge.classList.add("rag");
    badge.innerHTML =
      `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>` +
      `<span>RAG 기반 응답</span>`;
  } else {
    badge.classList.add("general");
    badge.innerHTML =
      `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>` +
      `<span>일반 응답</span>`;
  }

  // citation-list 위에 삽입
  const citationList = contentEl.querySelector(".citation-list");
  if (citationList) {
    contentEl.insertBefore(badge, citationList);
  } else {
    const copyBtn = contentEl.querySelector(".message-actions");
    if (copyBtn) {
      contentEl.insertBefore(badge, copyBtn);
    } else {
      contentEl.append(badge);
    }
  }
}

/* ── Citations ── */

function renderCitations(contentEl, citations = []) {
  const existing = contentEl.querySelector(".citation-list");
  if (existing) existing.remove();
  if (!citations.length) return;

  const list = document.createElement("div");
  list.className = "citation-list";

  for (const citation of citations) {
    const link = document.createElement("a");
    link.className = "citation-link";
    link.dataset.index = citation.index;

    const isExternal = citation.is_external;

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
    iconSpan.innerHTML = ICONS.doc;

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

/* ── Inline citation processing ── */

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
    if (/\[\d+\]/.test(node.textContent)) textNodes.push(node);
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
        badge.textContent = `${index}`;
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
          const isExternal = citation.is_external;
          if (!isExternal) showDocumentViewer(citation);
        });
        fragment.appendChild(badge);
      } else if (part) {
        fragment.appendChild(document.createTextNode(part));
      }
    }
    textNode.parentNode.replaceChild(fragment, textNode);
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
    if (done) break;
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
  for (const chunk of chunks) handleSseEvent(chunk, targetEl);
  return { remaining };
}

function handleSseEvent(rawEvent, targetEl) {
  const lines = rawEvent.split("\n");
  let eventName = "message";
  const dataLines = [];

  for (const line of lines) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }

  if (!dataLines.length) return;

  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    data = { delta: dataLines.join("\n") };
  }

  if (eventName === "metadata") return;

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
    const responseType = data.response_type || "general";
    renderMarkdown(targetEl, finalText);
    if (citations.length) {
      processInlineCitations(targetEl, citations);
    }
    renderAnswerableBadge(targetEl, responseType);
    renderCitations(targetEl.parentElement, citations);
    state.streamingText = "";
    scrollToBottom(_messagesEl);
    return;
  }

  if (eventName === "error") {
    hideTypingIndicator(targetEl);
    throw new Error(data.message || "SSE stream error");
  }
}

/* ── Send ── */

export async function sendMessage() {
  const message = _messageInput.value.trim();
  if (!message && !state.attachedFiles.length) return;

  setBusy(true);
  _setStatus?.("응답 대기 중");
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
    const fileIds = uploadedFiles.map((f) => f.id);

    appendMessage("user", message || "첨부 파일", uploadedFiles);
    _messageInput.value = "";
    autoResizeComposer();

    assistantContent = appendMessage("assistant", "");
    showTypingIndicator(assistantContent);

    await streamAssistantResponse(sessionId, message || "첨부 파일을 분석해줘.", fileIds, assistantContent);
    _setStatus?.("완료", "ok");
    await loadSessions();
  } catch (error) {
    _setStatus?.(formatError(error), "error");
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
    _messageInput?.focus();
  }
}

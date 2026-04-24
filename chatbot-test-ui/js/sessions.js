"use strict";

import { state } from "./state.js";
import { apiFetch } from "./api.js";
import { formatError } from "./utils.js";

/* ── DOM references ── */
let _sessionListEl, _sessionTitleEl;

export function initSessions(sessionListEl, sessionTitleEl) {
  _sessionListEl = sessionListEl;
  _sessionTitleEl = sessionTitleEl;
}

/* ── CRUD ── */

export async function createSession() {
  const response = await apiFetch("/v1/chat/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const session = await response.json();
  state.currentSessionId = session.session_id;
  await loadSessions();
  return session;
}

export async function ensureSession() {
  if (state.currentSessionId) return state.currentSessionId;
  const session = await createSession();
  return session.session_id;
}

export async function loadSessions() {
  const response = await apiFetch("/v1/chat/sessions");
  const body = await response.json();
  state.sessions = body.sessions || [];
  syncSessionTitleFromList();
  renderSessions();
}

export async function loadSessionDetail(sessionId, renderMessagesFn) {
  const response = await apiFetch(`/v1/chat/sessions/${sessionId}`);
  const detail = await response.json();
  state.currentSessionId = detail.session_id;
  if (_sessionTitleEl) _sessionTitleEl.textContent = detail.title || "새 채팅";
  renderSessions();
  if (renderMessagesFn) renderMessagesFn(detail.messages || []);
}

function syncSessionTitleFromList() {
  if (!state.currentSessionId || !_sessionTitleEl) return;
  const current = state.sessions.find(
    (s) => s.session_id === state.currentSessionId,
  );
  if (current) _sessionTitleEl.textContent = current.title || "새 채팅";
}

/* ── Rendering ── */

/** @param {Function} [onSelect] Called when user clicks a session */
let _onSelectCallback;

export function setOnSelectSession(fn) {
  _onSelectCallback = fn;
}

export function renderSessions() {
  if (!_sessionListEl) return;
  _sessionListEl.replaceChildren();

  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "채팅 내역이 없습니다";
    _sessionListEl.append(empty);
    return;
  }

  for (const session of state.sessions) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "session-btn";
    if (session.session_id === state.currentSessionId) {
      btn.classList.add("active");
    }
    btn.title = session.title || session.session_id;

    const label = document.createElement("span");
    label.className = "session-btn-label";
    label.textContent = session.title || "새 채팅";
    btn.append(label);

    btn.addEventListener("click", () => {
      if (_onSelectCallback) _onSelectCallback(session.session_id);
    });
    _sessionListEl.append(btn);
  }
}

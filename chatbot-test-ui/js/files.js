"use strict";

import { state } from "./state.js";
import { apiFetch, buildLinkUrl } from "./api.js";
import { formatFileSize, fileKindClass, fileKindLabel, ICONS } from "./utils.js";

/* ── DOM references ── */
let _filesListEl, _loadMoreBtn;

export function initFiles(filesListEl, loadMoreBtn) {
  _filesListEl = filesListEl;
  _loadMoreBtn = loadMoreBtn;

  if (_loadMoreBtn) {
    _loadMoreBtn.addEventListener("click", () => {
      loadFiles(false).catch(console.error);
    });
  }
}

/* ── API ── */

export async function loadFiles(reset = true) {
  if (reset) {
    state.files = [];
    state.filesCursor = null;
    state.filesHasMore = false;
  }
  const params = new URLSearchParams({ limit: "20" });
  if (state.filesCursor) params.set("cursor", state.filesCursor);

  try {
    const response = await apiFetch("/v1/files", { query: params.toString() });
    const body = await response.json();
    const newFiles = body.files || [];
    state.files = reset ? newFiles : [...state.files, ...newFiles];
    state.filesCursor = body.next_cursor || null;
    state.filesHasMore = body.has_more || false;
    renderFilesList();
  } catch (error) {
    console.warn("파일 목록 조회 실패:", error);
  }
}

export async function uploadSelectedFiles(files, sessionId) {
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
    uploaded.push(await response.json());
  }
  return uploaded;
}

/* ── Rendering ── */

function renderFilesList() {
  if (!_filesListEl) return;
  _filesListEl.replaceChildren();

  if (!state.files.length) {
    const empty = document.createElement("div");
    empty.className = "files-empty";
    empty.textContent = "업로드된 파일이 없습니다.";
    _filesListEl.append(empty);
    if (_loadMoreBtn) _loadMoreBtn.hidden = true;
    return;
  }

  for (const file of state.files) {
    _filesListEl.append(createFileListItem(file));
  }
  if (_loadMoreBtn) _loadMoreBtn.hidden = !state.filesHasMore;
}

function createFileListItem(file) {
  const item = document.createElement("div");
  item.className = "src-card";

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
  downloadLink.className = "src-card-delete";
  downloadLink.innerHTML = ICONS.download;
  downloadLink.title = "다운로드";

  item.append(info, downloadLink);
  return item;
}

/* ── File Cards (used in chat messages & composer) ── */

export function createFileCard(file, variant) {
  // 서버 응답 파일은 file_kind를 사용, 로컬 파일은 fallback
  const kindCss = file.file_kind
    ? `file-kind-${file.file_kind}`
    : fileKindClass(file.content_type || file.type || "", file.filename || file.name || "");
  const kindLabel = file.file_kind_label
    || fileKindLabel(file.content_type || file.type || "", file.filename || file.name || "");

  const card = document.createElement("div");
  card.className = `file-card ${variant} ${kindCss}`;

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
  type.textContent = kindLabel;

  meta.append(name, type);
  card.append(icon, meta);
  return card;
}

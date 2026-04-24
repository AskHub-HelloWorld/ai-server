"use strict";

import { state } from "./state.js";
import { apiFetch } from "./api.js";
import { formatFileSize, formatError, ICONS } from "./utils.js";
import { renderMarkdown } from "./markdown.js";
import { showDocumentViewer } from "./modal.js";
import { sleep } from "./utils.js";

/* ── DOM references ── */
let _sourceListEl, _sourceCountEl, _sourceStatusBar, _sourceStatusText;
let _sourceFileInput, _sourceUploadBtn;
let _repoSourceToggle, _repoSourceForm, _repoUrlInput, _repoBranchInput;

export function initSources({
  sourceList,
  sourceCount,
  sourceStatusBar,
  sourceStatusText,
  sourceFileInput,
  sourceUploadBtn,
  repoSourceToggle,
  repoSourceForm,
  repoUrlInput,
  repoBranchInput,
}) {
  _sourceListEl = sourceList;
  _sourceCountEl = sourceCount;
  _sourceStatusBar = sourceStatusBar;
  _sourceStatusText = sourceStatusText;
  _sourceFileInput = sourceFileInput;
  _sourceUploadBtn = sourceUploadBtn;
  _repoSourceToggle = repoSourceToggle;
  _repoSourceForm = repoSourceForm;
  _repoUrlInput = repoUrlInput;
  _repoBranchInput = repoBranchInput;

  if (_sourceUploadBtn) {
    _sourceUploadBtn.addEventListener("click", () => {
      if (!state.isSourceBusy) _sourceFileInput?.click();
    });
  }
  if (_sourceFileInput) {
    _sourceFileInput.addEventListener("change", () => {
      if (_sourceFileInput.files.length) addSelectedSource();
    });
  }
  if (_repoSourceToggle && _repoSourceForm) {
    _repoSourceToggle.addEventListener("click", () => {
      const willShow = _repoSourceForm.hidden;
      _repoSourceForm.hidden = !willShow;
      _repoSourceToggle.classList.toggle("active", willShow);
      if (willShow && _repoUrlInput) _repoUrlInput.focus();
    });
  }
  if (_repoSourceForm) {
    _repoSourceForm.addEventListener("submit", (e) => {
      e.preventDefault();
      addRepoSource();
    });
  }
}

/* ── Status helpers ── */

function setSourceBusy(isBusy) {
  state.isSourceBusy = isBusy;
  if (_sourceUploadBtn) _sourceUploadBtn.disabled = isBusy;
}

function setSourceStatus(message, type = "") {
  if (!_sourceStatusBar) return;
  _sourceStatusBar.hidden = !message;
  _sourceStatusText.textContent = message;
  _sourceStatusBar.classList.toggle("ok", type === "ok");
  _sourceStatusBar.classList.toggle("error", type === "error");
}

/* ── CRUD ── */

export async function loadSources() {
  const response = await apiFetch("/v1/sources");
  const body = await response.json();
  state.sources = body.sources || [];
  renderSourcesList();
  return state.sources;
}

async function addSelectedSource() {
  const file = _sourceFileInput.files[0];
  if (!file) {
    setSourceStatus("소스 파일을 선택하세요.", "error");
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
    if (completed.status === "succeeded") {
      setSourceStatus(
        `인덱싱 완료: ${uploaded.filename} · ${completed.indexed_object_count}개 chunk`,
        "ok",
      );
      _sourceFileInput.value = "";
    } else {
      setSourceStatus(completed.failure_reason || "인덱싱 실패", "error");
    }
  } catch (error) {
    setSourceStatus(formatError(error), "error");
  } finally {
    setSourceBusy(false);
  }
}

async function addRepoSource() {
  const repoUrl = _repoUrlInput?.value?.trim();
  if (!repoUrl) {
    setSourceStatus("Repository URL을 입력하세요.", "error");
    return;
  }
  const branch = _repoBranchInput?.value?.trim() || null;

  setSourceBusy(true);
  setSourceStatus("레포 소스 등록 중...");
  try {
    const response = await apiFetch("/v1/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_type: "repository",
        repo_url: repoUrl,
        default_branch: branch,
      }),
    });
    const source = await response.json();
    setSourceStatus("인덱싱 작업 생성 중...");
    const job = await createIngestionJob(source.source_id);
    setSourceStatus("인덱싱 중. worker가 실행 중이어야 합니다.");
    const completed = await waitForIngestionJob(job.job_id);
    await loadSources();
    if (completed.status === "succeeded") {
      setSourceStatus(
        `인덱싱 완료: ${source.name} · ${completed.indexed_object_count}개 chunk`,
        "ok",
      );
      if (_repoUrlInput) _repoUrlInput.value = "";
      if (_repoBranchInput) _repoBranchInput.value = "";
      if (_repoSourceForm) _repoSourceForm.hidden = true;
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
  while (true) {
    const response = await apiFetch(`/v1/ingestion-jobs/${jobId}`);
    const job = await response.json();
    if (job.is_terminal) return job;
    await sleep(2000);
  }
}

export async function reindexSource(sourceId) {
  setSourceBusy(true);
  setSourceStatus("재인덱싱 작업 생성 중...");
  try {
    const job = await createIngestionJob(sourceId);
    setSourceStatus("재인덱싱 중. worker가 실행 중이어야 합니다.");
    const completed = await waitForIngestionJob(job.job_id);
    await loadSources();
    if (completed.status === "succeeded") {
      setSourceStatus(
        `재인덱싱 완료: ${completed.indexed_object_count}개 chunk · 요약 생성됨`,
        "ok",
      );
    } else {
      setSourceStatus(completed.failure_reason || "재인덱싱 실패", "error");
    }
  } catch (error) {
    setSourceStatus(formatError(error), "error");
  } finally {
    setSourceBusy(false);
  }
}

export async function deleteSource(sourceId) {
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

/* ── Rendering ── */

export function renderSourcesList() {
  if (!_sourceListEl) return;
  _sourceListEl.replaceChildren();
  if (_sourceCountEl) _sourceCountEl.textContent = state.sources.length;

  if (!state.sources.length) {
    const empty = document.createElement("div");
    empty.className = "src-empty";
    empty.textContent = "등록된 소스가 없습니다.";
    _sourceListEl.append(empty);
    return;
  }

  for (const source of state.sources) {
    _sourceListEl.append(createSourceCard(source));
  }
}

function createSourceCard(source) {
  const card = document.createElement("div");
  card.className = "src-card";

  const info = document.createElement("div");
  info.className = "src-card-info";

  const icon = document.createElement("div");
  icon.className = "src-card-icon";
  icon.innerHTML = source.source_type === "repository" ? ICONS.repo : ICONS.doc;

  const metaBox = document.createElement("div");
  metaBox.className = "src-card-meta";

  const name = document.createElement("p");
  name.className = "src-card-name";
  name.textContent = source.name || source.source_id;
  name.title = name.textContent;

  const details = document.createElement("p");
  details.className = "src-card-details";
  details.textContent = `${source.type_label} · ${source.status_label} · ${source.chunk_count || 0} chunks`;

  metaBox.append(name, details);
  info.append(icon, metaBox);

  const actions = document.createElement("div");
  actions.className = "src-card-actions";

  // 재인덱싱 버튼 (ready 상태일 때만)
  if (source.status === "ready") {
    const reindexBtn = document.createElement("button");
    reindexBtn.type = "button";
    reindexBtn.className = "src-card-action-btn";
    reindexBtn.innerHTML = ICONS.refresh;
    reindexBtn.title = "재인덱싱 (요약 생성)";
    reindexBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      reindexSource(source.source_id);
    });
    actions.append(reindexBtn);
  }

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "src-card-action-btn src-card-delete";
  deleteBtn.innerHTML = ICONS.trash;
  deleteBtn.title = "삭제";
  deleteBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    deleteSource(source.source_id);
  });
  actions.append(deleteBtn);

  const header = document.createElement("div");
  header.className = "src-card-header";
  header.append(info, actions);
  card.append(header);

  // 요약 패널 (클릭으로 토글)
  if (source.status === "ready") {
    const summaryPanel = document.createElement("div");
    summaryPanel.className = "src-card-body";
    summaryPanel.hidden = true;

    if (source.summary) {
      const summaryContent = document.createElement("div");
      summaryContent.className = "src-card-summary";
      renderMarkdown(summaryContent, source.summary);
      summaryPanel.append(summaryContent);
    } else {
      const emptyMsg = document.createElement("p");
      emptyMsg.className = "src-card-summary--empty";
      emptyMsg.textContent = "요약이 아직 생성되지 않았습니다. 재인덱싱으로 생성할 수 있습니다.";
      summaryPanel.append(emptyMsg);
    }

    header.style.cursor = "pointer";
    header.addEventListener("click", () => {
      const willShow = summaryPanel.hidden;
      summaryPanel.hidden = !willShow;
      card.classList.toggle("expanded", willShow);
    });

    card.append(summaryPanel);
  }

  return card;
}

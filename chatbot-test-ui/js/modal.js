"use strict";

import { buildLinkUrl } from "./api.js";

/* ── DOM references (set once from main.js) ── */
let _modal, _title, _body;

export function initModal(modalEl, titleEl, bodyEl) {
  _modal = modalEl;
  _title = titleEl;
  _body = bodyEl;

  const backdrop = _modal.querySelector(".modal-backdrop");
  if (backdrop) backdrop.addEventListener("click", hideDocumentViewer);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !_modal.hidden) hideDocumentViewer();
  });
}

/* ── Citation URL ── */

function citationUrl(url) {
  if (!url) return "#";
  if (url.startsWith("/v1/")) return buildLinkUrl(url);
  return url;
}

/* ── Show / Hide ── */

export function showDocumentViewer(citation) {
  if (!citation) return;

  const isExternal = citation.is_external;
  if (isExternal) {
    window.open(citation.url, "_blank", "noreferrer");
    return;
  }

  _title.textContent = citation.title || citation.path || "문서 보기";
  _body.replaceChildren();

  const url = citationUrl(citation.url);

  if (url && url !== "#") {
    if (citation.viewer_type === "pdf") {
      const iframe = document.createElement("iframe");
      iframe.src = url;
      iframe.className = "doc-viewer-iframe";
      iframe.setAttribute("loading", "lazy");
      _body.append(iframe);
    } else {
      const loading = document.createElement("div");
      loading.className = "doc-viewer-loading";
      loading.textContent = "문서를 불러오는 중...";
      _body.append(loading);

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
          _body.replaceChildren();
          const pre = document.createElement("pre");
          pre.className = "doc-viewer-text";
          pre.textContent = text;
          _body.append(pre);
        })
        .catch(() => {
          _body.replaceChildren();
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
          _body.append(fallback);
        });
    }
  } else {
    const noContent = document.createElement("div");
    noContent.className = "doc-viewer-fallback";
    noContent.textContent = "문서 URL을 사용할 수 없습니다.";
    _body.append(noContent);
  }

  _modal.hidden = false;
  document.body.classList.add("modal-open");
}

export function hideDocumentViewer() {
  _modal.hidden = true;
  document.body.classList.remove("modal-open");
  _body.replaceChildren();
}

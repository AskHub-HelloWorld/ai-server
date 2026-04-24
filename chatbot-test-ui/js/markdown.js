"use strict";

import { state } from "./state.js";

/* ── Math Protection ── */

function protectMath(text) {
  const blocks = [];
  const ph = (i) => `%%MATH_${i}%%`;

  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_m, c) => {
    blocks.push({ content: c.trim(), display: true });
    return ph(blocks.length - 1);
  });
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_m, c) => {
    blocks.push({ content: c.trim(), display: true });
    return ph(blocks.length - 1);
  });
  text = text.replace(/\\\((.+?)\\\)/g, (_m, c) => {
    blocks.push({ content: c.trim(), display: false });
    return ph(blocks.length - 1);
  });
  text = text.replace(/\$([^\$\n]+?)\$/g, (_m, c) => {
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

/* ── Render ── */

/**
 * Parse markdown text into the given element. Supports KaTeX math.
 * Stores the raw source in `el.dataset.rawText` for copy-to-clipboard.
 */
export function renderMarkdown(el, text) {
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

/* ── Batched Streaming Render ── */

let _scheduled = false;
let _rafId = 0;

export function scheduleMarkdownRender(targetEl) {
  if (_scheduled) return;
  _scheduled = true;
  _rafId = requestAnimationFrame(() => {
    renderMarkdown(targetEl, state.streamingText);
    targetEl.closest(".messages")?.scrollTo({
      top: targetEl.closest(".messages")?.scrollHeight,
    });
    _scheduled = false;
    _rafId = 0;
  });
}

export function cancelPendingRender() {
  if (_rafId) {
    cancelAnimationFrame(_rafId);
    _rafId = 0;
    _scheduled = false;
  }
}

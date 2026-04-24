"use strict";

import { state } from "./state.js";

/* ── URL Builders ── */

export function buildUrl(path, query = "") {
  return `/api${path}${query ? `?${query}` : ""}`;
}

export function buildLinkUrl(path, query = "") {
  const params = new URLSearchParams(query);
  params.set("test_user_id", String(getUserId()));
  const teamId = getTeamId();
  if (teamId !== null) {
    params.set("test_team_id", String(teamId));
  }
  return buildUrl(path, params.toString());
}

/* ── Auth Helpers ── */

export function getUserId() {
  const el = document.querySelector("#userIdInput");
  const value = Number.parseInt(el?.value, 10);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error("User ID를 입력하세요.");
  }
  return value;
}

export function getTeamId() {
  const el = document.querySelector("#teamIdInput");
  const raw = el?.value?.trim();
  if (!raw) return null;
  const value = Number.parseInt(raw, 10);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error("Team ID는 비워두거나 1 이상의 숫자로 입력하세요.");
  }
  return value;
}

function getTestContextHeaders() {
  const userId = getUserId();
  const teamId = getTeamId();
  const headers = { "X-Test-User-Id": String(userId) };
  if (teamId !== null) {
    headers["X-Test-Team-Id"] = String(teamId);
  }
  return headers;
}

/* ── Core Fetch ── */

async function readErrorBody(response) {
  const ct = response.headers.get("content-type") || "";
  try {
    if (ct.includes("application/json")) {
      const body = await response.json();
      return typeof body.detail === "string" ? body.detail : JSON.stringify(body);
    }
    return await response.text();
  } catch {
    return "";
  }
}

/**
 * Authenticated fetch wrapper — injects test context headers and
 * handles non-ok responses by throwing enriched Error objects.
 */
export async function apiFetch(path, options = {}) {
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
    throw new Error(
      `${response.status} ${response.statusText}${detail ? ` — ${detail}` : ""}`,
    );
  }
  return response;
}

/* ── Health Check ── */

export async function healthCheck(setStatus) {
  try {
    const response = await fetch(buildUrl("/health"));
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const body = await response.json();

    let readyLabel = "";
    try {
      const readyRes = await fetch(buildUrl("/ready"));
      readyLabel = readyRes.ok ? " · ready" : " · not ready";
    } catch {
      /* ignore */
    }
    setStatus(`${body.status || "ok"} · ${body.version || "-"}${readyLabel}`, "ok");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error), "error");
  }
}

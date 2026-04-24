"use strict";

/**
 * Reactive state store with pub/sub notifications.
 * Each key change triggers registered callbacks.
 */
const _state = {
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

/** @type {Map<string, Set<Function>>} */
const _listeners = new Map();

export const state = new Proxy(_state, {
  set(target, key, value) {
    const prev = target[key];
    target[key] = value;
    if (prev !== value) {
      const fns = _listeners.get(key);
      if (fns) {
        for (const fn of fns) {
          try {
            fn(value, prev, key);
          } catch (err) {
            console.error(`[state] listener error for "${String(key)}":`, err);
          }
        }
      }
    }
    return true;
  },
});

/**
 * Subscribe to changes on a specific state key.
 * @param {string}   key
 * @param {Function} callback  (newValue, oldValue, key) => void
 * @returns {Function} unsubscribe
 */
export function subscribe(key, callback) {
  if (!_listeners.has(key)) {
    _listeners.set(key, new Set());
  }
  _listeners.get(key).add(callback);
  return () => _listeners.get(key)?.delete(callback);
}

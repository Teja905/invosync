import BACKEND from "./client";

const DB_NAME = "invosync-offline";
const STORE = "queue";
const KEY = "invosync-offline-queue";

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function save(items) {
  try {
    localStorage.setItem(KEY, JSON.stringify(items.slice(-50)));
  } catch {
    /* ignore quota */
  }
}

export function enqueue(entry) {
  const items = load();
  items.push({ ...entry, _ts: Date.now() });
  save(items);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated", { detail: items.length }));
  }
}

export function pendingCount() {
  return load().length;
}

export function clearQueue() {
  save([]);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated", { detail: 0 }));
  }
}

/**
 * Wrapped fetch that transparently queues mutations (POST/PUT/DELETE) when the
 * backend is unreachable and replays them (FIFO) when connectivity returns.
 * Read requests (GET) are not queued — they simply fail fast.
 */
export async function queuedFetch(path, options = {}, { replayable = true } = {}) {
  const method = (options.method || "GET").toUpperCase();
  try {
    const res = await fetch(`${BACKEND}${path}`, options);
    if (res.ok) return res;
    // 4xx/5xx — not a connectivity issue, surface normally
    if (!(res.status >= 500) && res.status !== 0) {
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    throw new Error("server-error");
  } catch (err) {
    const isNetwork = err.name === "TypeError" || err.message === "Failed to fetch" || err.message === "server-error";
    if (isNetwork && replayable && method !== "GET") {
      enqueue({ path, options, method });
      const e = new Error("queued-offline");
      e.queued = true;
      throw e;
    }
    throw err;
  }
}

/**
 * Replay all queued mutations in order. Returns { attempted, succeeded, failed }.
 */
export async function flushOfflineQueue(getAuthHeaders) {
  const items = load();
  if (!items.length) return { attempted: 0, succeeded: 0, failed: 0 };
  const results = { attempted: items.length, succeeded: 0, failed: 0 };
  const remaining = [];
  for (const item of items) {
    try {
      const opts = item.options || {};
      const headers = getAuthHeaders ? getAuthHeaders() : opts.headers;
      const res = await fetch(`${BACKEND}${item.path}`, { ...opts, headers });
      if (res.ok) results.succeeded += 1;
      else { results.failed += 1; remaining.push(item); }
    } catch {
      results.failed += 1;
      remaining.push(item);
    }
  }
  save(remaining);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("offline-queue-updated", { detail: remaining.length }));
  }
  return results;
}

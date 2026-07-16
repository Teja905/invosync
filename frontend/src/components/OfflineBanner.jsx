import { useEffect, useState, useCallback } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { pendingCount, flushOfflineQueue } from "../api/queue";

export default function OfflineBanner() {
  const { getAuthHeaders } = useAuth();
  const [offline, setOffline] = useState(false);
  const [lastSeen, setLastSeen] = useState(null);
  const [pending, setPending] = useState(0);
  const [flushing, setFlushing] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const refreshPending = useCallback(() => setPending(pendingCount()), []);

  useEffect(() => {
    window.addEventListener("offline-queue-updated", refreshPending);
    refreshPending();
    return () => window.removeEventListener("offline-queue-updated", refreshPending);
  }, [refreshPending]);

  const flush = useCallback(async () => {
    if (flushing) return;
    setFlushing(true);
    try {
      const res = await flushOfflineQueue(getAuthHeaders);
      setLastResult(res);
      refreshPending();
    } finally {
      setFlushing(false);
    }
  }, [flushing, getAuthHeaders, refreshPending]);

  useEffect(() => {
    let alive = true;

    async function check() {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 4000);
        const res = await fetch(`${BACKEND}/health`, { headers: getAuthHeaders(), signal: ctrl.signal });
        clearTimeout(t);
        if (!alive) return;
        if (res.ok) {
          const wasOffline = offline;
          setOffline(false);
          setLastSeen(new Date().toLocaleTimeString());
          // Auto-replay queued mutations once we're back online
          if (wasOffline && pendingCount() > 0) flush();
        } else {
          setOffline(true);
        }
      } catch {
        if (alive) setOffline(true);
      }
    }

    check();
    const interval = setInterval(check, 15000);
    window.addEventListener("online", check);
    return () => { alive = false; clearInterval(interval); window.removeEventListener("online", check); };
  }, [getAuthHeaders, flush]);

  if (!offline) return null;

  return (
    <div className="premium-alert premium-alert-error animate-fadeInUp" style={{ position: "sticky", top: 0, zIndex: 60, borderRadius: 0 }}>
      <span>⚠</span>
      <div className="flex-1">
        <p className="text-sm font-medium">Backend unreachable — working offline</p>
        <p className="text-xs opacity-80">
          Your work is saved locally{pending > 0 ? ` · ${pending} action${pending > 1 ? "s" : ""} queued` : ""}.{" "}
          They will sync automatically once the connection is restored.
        </p>
        {lastResult && (
          <p className="text-xs opacity-70">Last sync: {lastResult.succeeded} ok, {lastResult.failed} failed</p>
        )}
      </div>
      {pending > 0 && (
        <button className="btn btn-sm btn-ghost" disabled={flushing} onClick={flush}>
          {flushing ? "Syncing…" : "Retry now"}
        </button>
      )}
      {lastSeen && <span className="text-xs opacity-60">Last online: {lastSeen}</span>}
    </div>
  );
}

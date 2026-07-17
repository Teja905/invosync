import { createContext, useContext, useState, useCallback } from "react";

const ToastContext = createContext(null);

const KIND_CLASS = {
  success: "premium-alert-success",
  error: "premium-alert-error",
  warning: "premium-alert-warning",
  info: "premium-alert-info",
};

const ICON = { success: "✓", error: "✕", warning: "⚠", info: "ℹ" };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const push = useCallback((kind, message, ttl = 4000) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    if (ttl) setTimeout(() => dismiss(id), ttl);
    return id;
  }, [dismiss]);

  const api = {
    success: (m) => push("success", m),
    error: (m) => push("error", m, 6000),
    warning: (m) => push("warning", m),
    info: (m) => push("info", m),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed top-4 right-4 z-[80] flex flex-col gap-2 w-[min(92vw,360px)]">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`premium-alert ${KIND_CLASS[t.kind] || KIND_CLASS.info} animate-fadeInUp flex items-center gap-3 cursor-pointer`}
            onClick={() => dismiss(t.id)}
            role="status"
          >
            <span className="text-base leading-none">{ICON[t.kind] || ICON.info}</span>
            <span className="flex-1 text-sm">{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) return { success() {}, error() {}, warning() {}, info() {} };
  return ctx;
}

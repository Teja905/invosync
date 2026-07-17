export default function ConfirmDialog({ title, message, confirmLabel = "Confirm", danger = true, onConfirm, onCancel }) {
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeInUp"
      onClick={onCancel}
    >
      <div
        className="premium-card-flat p-6 w-full max-w-md space-y-4 animate-fadeInUp"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className="text-lg font-semibold text-[var(--premium-text-primary)]">{title}</h3>
        <p className="text-sm text-[var(--text-secondary)]">{message}</p>
        <div className="flex justify-end gap-3 pt-2">
          <button className="premium-btn-secondary text-sm px-4 py-2" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={
              danger
                ? "px-4 py-2 rounded-lg text-sm font-medium bg-[var(--accent-red)] text-white hover:opacity-80"
                : "premium-btn text-sm px-4 py-2"
            }
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

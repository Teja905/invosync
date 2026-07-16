import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";

export default function UploadPanel({ onUpload, extracting, extractionStatus }) {
  const [files, setFiles] = useState([]);

  const onDrop = useCallback((acceptedFiles) => {
    if (!acceptedFiles.length) return;
    const entries = acceptedFiles.map((file) => ({
      file, name: file.name, size: file.size, status: "pending", id: Date.now() + Math.random(),
    }));
    setFiles((prev) => [...entries, ...prev]);
    onUpload(acceptedFiles);
  }, [onUpload]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "image/*": [".png", ".jpg", ".jpeg", ".webp"], "application/pdf": [".pdf"] },
    disabled: extracting,
  });

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function statusBadge(status) {
    switch (status) {
      case "pending":
        return <span className="premium-badge premium-badge-neutral text-[10px]">Pending</span>;
      case "processing":
        return <span className="premium-badge premium-badge-info text-[10px] animate-pulse">Processing</span>;
      case "done":
        return <span className="premium-badge premium-badge-success text-[10px]">Done</span>;
      case "failed":
        return <span className="premium-badge premium-badge-danger text-[10px]">Failed</span>;
      case "duplicate":
        return <span className="premium-badge premium-badge-warning text-[10px]">Duplicate</span>;
      default:
        return <span className="premium-badge premium-badge-neutral text-[10px]">{status}</span>;
    }
  }

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={`premium-dropzone ${isDragActive ? "active" : ""}`}
      >
        <input {...getInputProps()} />
        {extracting ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
            <p className="text-gray-400">Extracting invoice data...</p>
          </div>
        ) : isDragActive ? (
          <p style={{ fontSize: "16px", fontWeight: 500, color: "var(--accent-blue)" }}>
            Drop invoices here
          </p>
        ) : (
          <div>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{ margin: "0 auto 16px", opacity: 0.4 }}>
              <path d="M12 3v12m0 0l-3-3m3 3l3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <rect x="3" y="15" width="18" height="2" rx="1" fill="currentColor" opacity="0.1"/>
            </svg>
            <p style={{ color: "var(--text-secondary)", fontSize: "14px", fontWeight: 500 }}>
              Drop invoice images or PDFs here
            </p>
            <p style={{ color: "var(--text-tertiary)", fontSize: "12px", marginTop: "4px" }}>
              or click to browse &bull; PNG, JPG, WebP, PDF &bull; Drop multiple at once
            </p>
          </div>
        )}
      </div>

      {files.length > 0 && (
        <div className="premium-card-flat overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5 text-left text-xs text-gray-500 uppercase">
                <th className="px-3 py-2 font-medium">File</th>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {files.map((f) => (
                <tr key={f.id} className="premium-table-row">
                  <td className="px-3 py-2.5 text-gray-200 text-xs truncate max-w-[200px]">{f.name}</td>
                  <td className="px-3 py-2.5 text-gray-400 text-xs">{formatSize(f.size)}</td>
                  <td className="px-3 py-2.5 text-right">{statusBadge(f.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function TallyConnectorPanel() {
  const downloadUrl = "https://github.com/Teja905/invosync/releases/latest/download/InvoSyncTallyConnector-v3.2.zip";
  return (
    <div className="premium-card-flat p-6 max-w-2xl">
      <div className="flex items-start gap-4">
        <div className="p-3 rounded-lg" style={{background:"var(--accent-alpha)", color:"var(--accent)"}}>
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-gray-200">InvoSync Tally Connector</h3>
          <p className="mt-1 text-xs text-gray-500">
            Run this lightweight assistant on the PC that has Tally Prime to auto-import XML vouchers. Tally must be open with connectivity port <strong>9000</strong> enabled (F1 &rarr; Settings &rarr; Connectivity).
          </p>
          <div className="mt-4 flex items-center gap-3">
            <a href={downloadUrl} download
               className="premium-btn-primary inline-flex items-center gap-2 text-sm py-2.5 px-5">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download Tally Connector
            </a>
            <span className="text-xs text-gray-600">Version 3.2 &bull; 72 MB</span>
          </div>
        </div>
      </div>
    </div>
  );
}

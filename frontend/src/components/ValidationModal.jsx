export default function ValidationModal({
  show, data, onGenerateAnyway, onClose, onFixAll, onApplyFix,
}) {
  if (!show || !data) return null;

  const suggestions = data.fix_suggestions || [];

  return (
    <div className="premium-modal-overlay" onClick={onClose}>
      <div className="premium-modal" style={{padding:"24px", maxWidth:"520px"}} onClick={(e) => e.stopPropagation()}>
        <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"16px"}}>
          <h3 style={{fontSize:"16px", fontWeight:600, display:"flex", alignItems:"center", gap:"8px"}}>
            <span>{'\u26A0'}</span> Validation Results
          </h3>
          <button onClick={onClose} style={{color:"var(--text-tertiary)", background:"none", border:"none", fontSize:"20px", cursor:"pointer"}}>&times;</button>
        </div>

        {/* Blocking errors */}
        {data.blocking_errors?.length > 0 && (
          <div style={{marginBottom:"12px"}}>
            <p className="premium-badge premium-badge-danger" style={{marginBottom:"6px"}}>
              {data.blocking_errors.length} Blocking Error{data.blocking_errors.length > 1 ? "s" : ""}
            </p>
            {data.blocking_errors.map((e, i) => (
              <p key={i} style={{fontSize:"12px", color:"var(--accent-red)", paddingLeft:"8px", borderLeft:"2px solid rgba(248,81,73,0.3)", marginBottom:"4px"}}>{e}</p>
            ))}
          </div>
        )}

        {/* Soft errors */}
        {data.soft_errors?.length > 0 && (
          <div style={{marginBottom:"12px"}}>
            <p className="premium-badge premium-badge-warning" style={{marginBottom:"6px"}}>Soft Errors (overridable)</p>
            {data.soft_errors.map((e, i) => (
              <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{e}</p>
            ))}
          </div>
        )}

        {/* Warnings */}
        {data.warnings?.length > 0 && (
          <div style={{marginBottom:"12px"}}>
            <p className="premium-badge premium-badge-neutral" style={{marginBottom:"6px"}}>Warnings</p>
            {data.warnings.map((w, i) => (
              <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{w}</p>
            ))}
          </div>
        )}

        {/* Fix suggestions */}
        {suggestions.length > 0 && (
          <div style={{marginBottom:"16px"}}>
            <p className="premium-badge premium-badge-info" style={{marginBottom:"6px"}}>
              Suggested Fixes ({suggestions.length})
            </p>
            <div className="space-y-2">
              {suggestions.map((s, i) => (
                <div key={i} style={{
                  fontSize:"12px", padding:"8px 10px", background:"rgba(99,102,241,0.08)",
                  borderRadius:"6px", border:"1px solid rgba(99,102,241,0.15)",
                }}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p style={{color:"var(--accent-red)", fontWeight:500, marginBottom:"2px"}}>{s.message}</p>
                      <p style={{color:"var(--text-tertiary)", fontSize:"11px"}}>
                        {s.fix_type === "create_ledger" && "Create missing ledger in Tally"}
                        {s.fix_type === "correct_gstin" && "Auto-correct GSTIN format"}
                        {s.fix_type === "set_field" && "Enter the missing value"}
                        {s.fix_type === "auto_detect" && "Auto-detect from available data"}
                        {![ "create_ledger", "correct_gstin", "set_field", "auto_detect"].includes(s.fix_type) && s.fix_type}
                      </p>
                    </div>
                    <button
                      onClick={() => onApplyFix && onApplyFix(s)}
                      className="premium-btn-primary text-xs px-2.5 py-1 shrink-0"
                      style={{fontSize:"11px"}}
                    >
                      {s.fix_label}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{display:"flex", gap:"8px", paddingTop:"8px", flexDirection:"column"}}>
          {suggestions.length > 0 && onFixAll && (
            <button onClick={onFixAll}
              className="premium-btn premium-btn-primary"
              style={{flex:1, justifyContent:"center", padding:"10px", background:"var(--accent-green)"}}>
              {'\u26A1'} Fix All Automatically
            </button>
          )}
          <div style={{display:"flex", gap:"8px"}}>
            <button onClick={onGenerateAnyway}
              className="premium-btn premium-btn-primary" style={{flex:1, justifyContent:"center", padding:"10px"}}>
              Generate Anyway
            </button>
            <button onClick={onClose}
              className="premium-btn premium-btn-secondary" style={{flex:1, justifyContent:"center", padding:"10px"}}>
              Back to Edit
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

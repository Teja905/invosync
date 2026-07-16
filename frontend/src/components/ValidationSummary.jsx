export default function ValidationSummary({ validation }) {
  if (!validation) return null;
  const checks = Object.entries(validation.checks || {});
  const passed = checks.filter(([, r]) => r.pass).length;
  const total = checks.length;
  const warnings = validation.warnings || [];
  const softErrors = validation.soft_errors || [];
  const blockingErrors = validation.blocking_errors || [];
  const statutoryChecks = ["statutory_routing", "gst_structure", "gstin", "tax_rates"];
  return (
    <div className="premium-card" style={{padding:"16px"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"12px"}}>
        <div style={{display:"flex", alignItems:"center", gap:"8px"}}>
          <span style={{fontSize:"12px", color:"var(--text-secondary)"}}>Document:</span>
          <span style={{fontSize:"13px", fontWeight:600, textTransform:"capitalize"}}>{(validation.document_type || "unknown").replace(/_/g, " ")}</span>
        </div>
        <span className={`premium-badge ${validation.passed ? "premium-badge premium-badge-success" : "premium-badge premium-badge-danger"}`}>
          {validation.passed ? "PASS" : "FAIL"}
        </span>
      </div>
      <div style={{display:"flex", flexWrap:"wrap", gap:"6px", marginBottom:"12px"}}>
        {checks.map(([name, result]) => {
          const isStatutory = statutoryChecks.includes(name);
          return (
            <div key={name} className={`premium-badge ${
              result.pass ? (result.warnings?.length ? "premium-badge premium-badge-warning" : isStatutory ? "premium-badge premium-badge-info" : "premium-badge premium-badge-success") : "premium-badge premium-badge-danger"
            }`}>
              <span>{result.pass ? (result.warnings?.length ? "\u26A0" : "\u2713") : "\u2717"}</span>
              <span className="capitalize">{name.replace(/_/g, " ")}</span>
            </div>
          );
        })}
      </div>
      {warnings.length > 0 && (
        <div style={{marginBottom:"8px"}}>
          <p className="premium-badge premium-badge-warning" style={{marginBottom:"6px"}}>Warnings</p>
          {warnings.map((w, i) => (
            <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{w}</p>
          ))}
        </div>
      )}
      {softErrors.length > 0 && (
        <div style={{marginBottom:"8px"}}>
          <p className="premium-badge premium-badge-warning" style={{marginBottom:"6px"}}>Soft Errors</p>
          {softErrors.map((e, i) => (
            <p key={i} style={{fontSize:"12px", color:"var(--accent-yellow)", paddingLeft:"8px", borderLeft:"2px solid rgba(210,153,34,0.3)", marginBottom:"4px"}}>{e}</p>
          ))}
        </div>
      )}
      {blockingErrors.length > 0 && (
        <div>
          <p className="premium-badge premium-badge-danger" style={{marginBottom:"6px"}}>Blocking Errors</p>
          {blockingErrors.map((e, i) => (
            <p key={i} style={{fontSize:"12px", color:"var(--accent-red)", paddingLeft:"8px", borderLeft:"2px solid rgba(248,81,73,0.3)", marginBottom:"4px"}}>{e}</p>
          ))}
        </div>
      )}
    </div>
  );
}

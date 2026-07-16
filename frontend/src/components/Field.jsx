export default function Field({ label, error, children, optional }) {
  return (
    <div>
      <label className="premium-section-label">
        {label}
        {optional && <span className="premium-label-optional">(optional)</span>}
      </label>
      {children}
      {error && <p className="gh-error"><span>&#9888;</span>{error}</p>}
    </div>
  );
}

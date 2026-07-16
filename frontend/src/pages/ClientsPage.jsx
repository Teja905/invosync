import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

export default function ClientsPage({ refreshKey }) {
  const { getAuthHeaders } = useAuth();
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [clientName, setClientName] = useState("");
  const [gstin, setGstin] = useState("");
  const [editingClient, setEditingClient] = useState(null);
  const [editCompanyName, setEditCompanyName] = useState("");
  const [editClientName, setEditClientName] = useState("");
  const [editGstin, setEditGstin] = useState("");

  useEffect(() => {
    setLoading(true);
    fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setClients).catch(() => {}).finally(() => setLoading(false));
  }, [refreshKey]);

  async function addClient() {
    if (!companyName || !clientName) return;
    try {
      const r = await fetch(`${BACKEND}/clients`, {
        method: "POST", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ company_name: companyName, client_name: clientName, gstin }),
      });
      if (!r.ok) { const err = await r.text(); alert("Failed: " + err); return; }
      setCompanyName(""); setClientName(""); setGstin(""); setShowForm(false);
      const res = await fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error(await res.text());
      setClients(await res.json());
    } catch (e) { alert("Failed: " + e.message); }
  }

  function startEdit(c) {
    setEditingClient(c);
    setEditCompanyName(c.company_name);
    setEditClientName(c.client_name);
    setEditGstin(c.gstin || "");
  }

  function cancelEdit() {
    setEditingClient(null);
    setEditCompanyName(""); setEditClientName(""); setEditGstin("");
  }

  async function saveEdit() {
    if (!editCompanyName || !editClientName || !editingClient) return;
    try {
      await fetch(`${BACKEND}/clients/${editingClient.client_id}`, {
        method: "PUT", headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ company_name: editCompanyName, client_name: editClientName, gstin: editGstin }),
      });
      cancelEdit();
      const res = await fetch(`${BACKEND}/clients`, { headers: getAuthHeaders() });
      setClients(await res.json());
    } catch (e) { alert("Failed: " + e.message); }
  }

  async function deleteClient(id) {
    if (!window.confirm("Delete this client and ALL their invoices?")) return;
    try {
      await fetch(`${BACKEND}/clients/${id}`, { method: "DELETE", headers: getAuthHeaders() });
      setClients((prev) => prev.filter((c) => c.client_id !== id));
    } catch (e) { alert("Failed: " + e.message); }
  }

  if (loading) return <div className="text-center py-20"><div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-4 animate-fadeInUp">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold premium-gradient-text">Clients ({clients.length})</h2>
        <button onClick={() => setShowForm(!showForm)} className="premium-btn-primary text-sm px-4 py-2">
          {showForm ? "Cancel" : "+ Add Client"}
        </button>
      </div>

      {showForm && (
        <div className="premium-card-flat p-5 space-y-4 animate-fadeInUp">
          <h3 className="text-sm font-semibold text-gray-200">New Client</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Company Name *</label>
              <input className="input w-full" value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="e.g. ABC Traders" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Contact Person *</label>
              <input className="input w-full" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="e.g. Rajesh Kumar" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">GSTIN <span className="text-gray-600">(optional)</span></label>
              <input className="input w-full" value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} placeholder="Leave blank if N/A" />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setShowForm(false)} className="premium-btn-secondary text-sm px-4 py-2">Cancel</button>
            <button onClick={addClient} className="premium-btn-primary text-sm px-4 py-2">Save Client</button>
          </div>
        </div>
      )}

      {editingClient && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeInUp" onClick={cancelEdit}>
          <div className="premium-card-flat p-5 space-y-4 w-full max-w-lg animate-fadeInUp" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-gray-200">Edit Client</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Company Name *</label>
                <input className="input w-full" value={editCompanyName} onChange={(e) => setEditCompanyName(e.target.value)} placeholder="e.g. ABC Traders" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Contact Person *</label>
                <input className="input w-full" value={editClientName} onChange={(e) => setEditClientName(e.target.value)} placeholder="e.g. Rajesh Kumar" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">GSTIN <span className="text-gray-600">(optional)</span></label>
                <input className="input w-full" value={editGstin} onChange={(e) => setEditGstin(e.target.value.toUpperCase())} placeholder="Leave blank if N/A" />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={cancelEdit} className="premium-btn-secondary text-sm px-4 py-2">Cancel</button>
              <button onClick={saveEdit} className="premium-btn-primary text-sm px-4 py-2">Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {clients.length === 0 ? (
        <div className="premium-card" style={{padding:"48px 20px", textAlign:"center"}}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" style={{margin:"0 auto 16px", opacity:0.3}}>
            <path d="M3 7V5a2 2 0 012-2h14a2 2 0 012 2v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V7" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M3 7h18" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M9 12h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <p style={{color:"var(--text-secondary)", fontSize:"16px", marginBottom:"4px"}}>No clients yet</p>
          <p style={{color:"var(--text-tertiary)", fontSize:"13px"}}>Add your first client to start processing invoices.</p>
        </div>
      ) : (
        <div className="premium-card">
          <table className="premium-table">
            <thead><tr>
              <th>Company</th>
              <th>Contact</th>
              <th>GSTIN</th>
              <th>Invoices</th>
              <th>Action</th>
            </tr></thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.client_id} className="premium-table-row">
                  <td>{c.company_name}</td>
                  <td>{c.client_name}</td>
                  <td className="font-mono text-xs">{c.gstin || <span className="text-tertiary">N/A</span>}</td>
                  <td>{c.invoice_count || 0}</td>
                  <td className="flex gap-2">
                    <button onClick={() => startEdit(c)} className="text-xs" style={{color:"var(--accent-blue)"}}>Edit</button>
                    <button onClick={() => deleteClient(c.client_id)} className="text-xs" style={{color:"var(--accent-red)"}}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

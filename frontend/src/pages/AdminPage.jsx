import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";

export default function AdminPage() {
  const { getAuthHeaders } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND}/auth/admin/users`, { headers: getAuthHeaders() })
      .then((r) => r.json()).then(setUsers).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-20"><div className="w-8 h-8 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-4 animate-fadeInUp">
      <h2 className="text-lg font-bold premium-gradient-text">Users ({users.length})</h2>
      <div className="premium-card-flat overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-white/5 text-left text-xs text-gray-500 uppercase">
            <th className="px-4 py-3.5 font-medium">Email</th>
            <th className="px-4 py-3.5 font-medium">Name</th>
            <th className="px-4 py-3.5 font-medium">Role</th>
            <th className="px-4 py-3.5 font-medium text-center">Invoices</th>
            <th className="px-4 py-3.5 font-medium">Joined</th>
          </tr></thead>
          <tbody className="divide-y divide-white/5">
            {users.map((u) => (
              <tr key={u.email} className="premium-table-row">
                <td className="px-4 py-3.5 font-medium text-gray-200">{u.email}</td>
                <td className="px-4 py-3.5 text-gray-300">{u.name || "-"}</td>
                <td className="px-4 py-3.5"><span className={`premium-badge ${u.role === "admin" ? "premium-badge premium-badge-warning" : "premium-badge premium-badge-success"}`}>{u.role}</span></td>
                <td className="px-4 py-3.5 text-center text-gray-400">{u.invoice_count || 0}</td>
                <td className="px-4 py-3.5 text-xs text-gray-500">{u.created_at ? u.created_at.slice(0, 10) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import BACKEND from "../api/client";
import { useToast } from "../components/Toast";

export default function ClientLoginPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) throw new Error("Invalid credentials");
      const data = await res.json();
      localStorage.setItem("client_token", data.token);
      localStorage.setItem("client_user", JSON.stringify(data.user));
      toast.success("Welcome to your portal!");
      navigate("/client/dashboard");
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="premium-card-flat p-8 w-full max-w-md space-y-6">
        <div className="text-center">
          <div className="premium-logo-icon mx-auto mb-2">C</div>
          <h1 className="text-xl font-semibold text-white">Client Portal</h1>
          <p className="text-gray-400 text-sm mt-1">View your financial reports</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="email" placeholder="Email" value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="premium-input w-full" required
          />
          <input
            type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="premium-input w-full" required
          />
          <button type="submit" disabled={loading} className="premium-btn-primary w-full py-2.5">
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
        <p className="text-gray-500 text-xs text-center">
          Provided by your CA firm via InvoSync. Contact your accountant if you don't have access.
        </p>
      </div>
    </div>
  );
}

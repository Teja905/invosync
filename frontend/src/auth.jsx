import { createContext, useContext, useState, useEffect, useCallback } from "react";

const BACKEND = import.meta.env.VITE_API_URL || (
  window.location.hostname === "localhost" ? "" : "https://invosync-backend-yjfa.onrender.com"
);
const AuthContext = createContext(null);

const TOKEN_KEY = "invosync_token";
const USER_KEY = "invosync_user";

function loadToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

function loadUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveSession(token, user) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {}
}

function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {}
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => loadUser());
  const [token, setToken] = useState(() => loadToken());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedToken = loadToken();
    if (!storedToken) { setLoading(false); return; }
    fetch(`${BACKEND}/auth/me`, { headers: { Authorization: `Bearer ${storedToken}` } })
      .then((r) => {
        if (!r.ok) throw new Error("Invalid");
        return r.json();
      })
      .then((data) => {
        setUser(data);
        setToken(storedToken);
        saveSession(storedToken, data);
      })
      .catch(() => {
        clearSession();
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${BACKEND}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    saveSession(data.token, data.user);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  }, []);

  const signup = useCallback(async (email, password, name) => {
    const res = await fetch(`${BACKEND}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Signup failed");
    }
    const data = await res.json();
    saveSession(data.token, data.user);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setToken(null);
    setUser(null);
  }, []);

  const getAuthHeaders = useCallback(() => {
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
  }, [token]);

  const hasRole = useCallback((role) => {
    return user?.role === role;
  }, [user]);

  const refreshUser = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${BACKEND}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        setUser(data);
        saveSession(token, data);
      }
    } catch {}
  }, [token]);

  const ctx = {
    user,
    token,
    loading,
    isAuthenticated: !!user,
    login,
    signup,
    logout,
    getAuthHeaders,
    hasRole,
    refreshUser,
    BACKEND,
  };

  return <AuthContext.Provider value={ctx}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

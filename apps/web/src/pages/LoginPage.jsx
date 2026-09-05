import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const ROLE_REDIRECT = {
  analyst: "/analyst",
  supervisor: "/supervisor",
  admin: "/admin",
};

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const user = await login(email, password);
      navigate(ROLE_REDIRECT[user.role] || "/");
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-icon-lg">🛢</span>
          <h1>Marine Oil-Spill Attribution Platform</h1>
          <p className="login-subtitle">Satellite + AIS Detection & Source Attribution System</p>
        </div>
        <form onSubmit={handleSubmit}>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@oilspill.gov"
            required
            autoFocus
          />
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
            required
          />
          {error && <div className="login-error">{error}</div>}
          <button type="submit" disabled={loading}>
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
        <div className="login-demo">
          <p>Demo Credentials:</p>
          <div className="demo-creds">
            <div><strong>Analyst:</strong> analyst@oilspill.gov / analyst123</div>
            <div><strong>Supervisor:</strong> supervisor@oilspill.gov / super123</div>
            <div><strong>Admin:</strong> admin@oilspill.gov / admin123</div>
          </div>
        </div>
      </div>
    </div>
  );
}

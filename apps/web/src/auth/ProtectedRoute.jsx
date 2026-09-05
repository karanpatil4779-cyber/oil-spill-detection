import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function ProtectedRoute({ children, roles }) {
  const { user, loading } = useAuth();

  if (loading) return <div className="loading-screen">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) {
    const redirectMap = { analyst: "/analyst", supervisor: "/supervisor", admin: "/admin" };
    return <Navigate to={redirectMap[user.role] || "/login"} replace />;
  }
  return children;
}

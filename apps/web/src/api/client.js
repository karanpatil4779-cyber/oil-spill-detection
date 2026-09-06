const API_URL = import.meta.env.VITE_API_URL || "/api";

let _token = localStorage.getItem("token") || null;

export function setToken(token) {
  _token = token;
  if (token) localStorage.setItem("token", token);
  else localStorage.removeItem("token");
}

export function getToken() {
  return _token;
}

export function clearToken() {
  _token = null;
  localStorage.removeItem("token");
}

export async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (_token) headers["Authorization"] = `Bearer ${_token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) throw new Error(data.detail || `API error ${res.status} ${res.statusText}`.trim());
  return data;
}

export function apiGet(path) {
  return api(path, { method: "GET" });
}

export function apiPost(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

export function apiPatch(path, body) {
  return api(path, { method: "PATCH", body: JSON.stringify(body) });
}

export function apiPut(path, body) {
  return api(path, { method: "PUT", body: JSON.stringify(body) });
}

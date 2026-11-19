/* ============================================================
   Active Life Medical — Authentication & Session Management
   Backend-powered: users, passwords, and tokens live on the
   FastAPI backend.  This module wraps fetch() calls and stores
   JWT access/refresh tokens plus user info in localStorage.
   ============================================================ */

/* exported registerUser, loginUser, setSession, getSession, isLoggedIn, logoutUser, redirectToLogin, getNextUrl, authFetch */
/* global API_BASE */
const TOKEN_KEY = "md_tokens";   // { access_token, refresh_token }
const USER_KEY  = "md_user";     // { id, name, email, created_at }

/* ---- token helpers ---- */

function saveTokens(tokens) {
  localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
}

function getTokens() {
  try {
    return JSON.parse(localStorage.getItem(TOKEN_KEY));
  } catch (e) {
    return null;
  }
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
}

function saveUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clearUser() {
  localStorage.removeItem(USER_KEY);
}

/* ---- authFetch: auto-attach token, handle 401 with refresh ---- */

async function authFetch(url, options = {}) {
  const tokens = getTokens();
  if (!tokens) {
    throw new Error("Not authenticated");
  }

  const headers = { ...(options.headers || {}) };
  headers["Authorization"] = `Bearer ${tokens.access_token}`;
  if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  let response = await fetch(url, { ...options, headers });

  // If 401, try refreshing the token once
  if (response.status === 401 && tokens.refresh_token) {
    try {
      const refreshResponse = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });

      if (refreshResponse.ok) {
        const data = await refreshResponse.json();
        saveTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
        saveUser(data.user);

        // Retry original request with new token
        headers["Authorization"] = `Bearer ${data.access_token}`;
        response = await fetch(url, { ...options, headers });
      } else {
        // Refresh failed — log out
        clearTokens();
        clearUser();
        throw new Error("Session expired");
      }
    } catch (e) {
      clearTokens();
      clearUser();
      throw new Error("Session expired");
    }
  }

  return response;
}

/* ---- registration ---- */

async function registerUser({ name, email, password }) {
  if (!name || !email || !password) {
    return { ok: false, error: "All fields are required." };
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return { ok: false, error: "Enter a valid email address." };
  }
  if (password.length < 8) {
    return { ok: false, error: "Password must be at least 8 characters." };
  }

  try {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), email: email.trim().toLowerCase(), password }),
    });

    const data = await response.json();

    if (!response.ok) {
      return { ok: false, error: data.detail || "Registration failed." };
    }

    // Save tokens and user
    saveTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
    saveUser(data.user);

    return { ok: true, user: data.user };
  } catch (e) {
    return { ok: false, error: "Network error. Please try again." };
  }
}

/* ---- login ---- */

async function loginUser({ email, password }) {
  if (!email || !password) {
    return { ok: false, error: "Email and password are required." };
  }

  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
    });

    const data = await response.json();

    if (!response.ok) {
      return { ok: false, error: data.detail || "Incorrect email or password." };
    }

    // Save tokens and user
    saveTokens({ access_token: data.access_token, refresh_token: data.refresh_token });
    saveUser(data.user);

    return { ok: true, user: data.user };
  } catch (e) {
    return { ok: false, error: "Network error. Please try again." };
  }
}

/* ---- session ---- */

function getSession() {
  const user = getTokens() ? getStoredUser() : null;
  if (!user) return null;
  return {
    userId: user.id,
    name: user.name,
    email: user.email,
  };
}

function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY));
  } catch (e) {
    return null;
  }
}

function isLoggedIn() {
  return !!getTokens();
}

function logoutUser() {
  clearTokens();
  clearUser();
  // Also clear any cart data for the old user
  try {
    const keys = Object.keys(localStorage);
    keys.forEach(k => {
      if (k.startsWith("md_cart_")) localStorage.removeItem(k);
    });
  } catch (e) { /* ignore */ }
}

/* ---- redirect helpers for protected actions ---- */

function redirectToLogin(reason) {
  const next = encodeURIComponent(location.pathname.split("/").pop() + location.search);
  const msg = reason ? `&msg=${encodeURIComponent(reason)}` : "";
  location.href = `login.html?next=${next}${msg}`;
}

function getNextUrl(fallback) {
  const params = new URLSearchParams(location.search);
  const next = params.get("next");
  if (next && isSafeNextUrl(next)) {
    return next;
  }
  return fallback || "index.html";
}

function isSafeNextUrl(next) {
  try {
    const url = new URL(next, location.href);
    return url.protocol === location.protocol && url.host === location.host;
  } catch (e) {
    return false;
  }
}

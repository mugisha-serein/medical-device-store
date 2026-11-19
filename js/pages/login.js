/* ============================================================
   Active Life Medical — Login page: contextual message, session bounce,
   and form handling. Uses async API calls for authentication.
   ============================================================ */

/* global isLoggedIn, getNextUrl, loginUser, currentNextQuery, validateFields, attachLiveValidation, attachPasswordToggle */

const LOGIN_FIELDS = ["email", "password"];

const LOGIN_RULES = {
  email: value => (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? "" : "Enter a valid email address."),
  password: value => (value ? "" : "Enter your password.")
};

// Live per-field feedback (shared with register/checkout — see js/forms.js).
attachLiveValidation(LOGIN_FIELDS, LOGIN_RULES);
attachPasswordToggle("password");

// Show a contextual message if the user was redirected here from a protected action
const params = new URLSearchParams(location.search);
const msg = params.get("msg");
const msgBox = document.getElementById("form-msg");
if (msg) {
  msgBox.textContent = msg;
  msgBox.className = "form-msg show info";
}

// Carry the intended destination over if the user switches to create-account
const nextQuery = currentNextQuery();
if (nextQuery) {
  const registerLink = document.querySelector('.auth-switch a[href="register.html"]');
  if (registerLink) registerLink.href = `register.html${nextQuery}`;
}

// If already logged in, bounce straight to the intended page
if (isLoggedIn()) {
  location.href = getNextUrl("index.html");
}

const form = document.getElementById("login-form");
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const errors = validateFields(LOGIN_FIELDS, LOGIN_RULES);
  if (errors.length > 0) {
    msgBox.textContent = errors[0];
    msgBox.className = "form-msg show error";
    return;
  }

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  const result = await loginUser({ email, password });
  if (!result.ok) {
    msgBox.textContent = result.error;
    msgBox.className = "form-msg show error";
    return;
  }

  msgBox.textContent = "Login successful — redirecting…";
  msgBox.className = "form-msg show success";
  setTimeout(() => {
    location.href = getNextUrl("index.html");
  }, 500);
});

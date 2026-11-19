/* ============================================================
   Active Life Medical — Registration page: validation and account creation.
   Uses async API calls for registration.
   ============================================================ */

/* global isLoggedIn, registerUser, getNextUrl, currentNextQuery, validateFields, attachLiveValidation, attachPasswordToggle */

const REGISTER_FIELDS = ["name", "email", "password", "confirm"];

const REGISTER_RULES = {
  name: value => (value ? "" : "Enter your full name."),
  email: value => (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? "" : "Enter a valid email address."),
  password: () => (document.getElementById("password").value.length >= 8 ? "" : "Password must be at least 8 characters."),
  confirm: () => (document.getElementById("confirm").value === document.getElementById("password").value ? "" : "Passwords do not match.")
};

// Live per-field feedback (shared with login/checkout — see js/forms.js).
attachLiveValidation(REGISTER_FIELDS, REGISTER_RULES);
attachPasswordToggle("password");
attachPasswordToggle("confirm");

/* ---- password strength meter (live, independent of validation) ---- */

const STRENGTH_LABELS = ["", "Weak", "Fair", "Good", "Strong"];

function passwordStrengthLevel(password) {
  let score = 0;
  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++;
  if (/\d/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  if (score <= 1) return 1;
  if (score === 2) return 2;
  if (score === 3) return 3;
  return 4;
}

function updateStrengthMeter() {
  const meter = document.getElementById("strength-meter");
  const label = document.getElementById("strength-label");
  const password = document.getElementById("password").value;
  meter.hidden = !password;
  if (!password) {
    meter.dataset.level = "0";
    label.textContent = "";
    return;
  }
  const level = passwordStrengthLevel(password);
  meter.dataset.level = String(level);
  label.textContent = STRENGTH_LABELS[level];
}

document.getElementById("password").addEventListener("input", updateStrengthMeter);

// If already logged in, bounce to the intended page
if (isLoggedIn()) {
  location.href = getNextUrl("index.html");
}

// Carry the intended destination over if the user switches back to log in.
const nextQuery = currentNextQuery();
if (nextQuery) {
  const loginLink = document.querySelector('.auth-switch a[href="login.html"]');
  if (loginLink) loginLink.href = `login.html${nextQuery}`;
}

const msgBox = document.getElementById("form-msg");
const form = document.getElementById("register-form");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msgBox.className = "form-msg";

  const errors = validateFields(REGISTER_FIELDS, REGISTER_RULES);
  if (errors.length > 0) {
    msgBox.textContent = errors[0];
    msgBox.className = "form-msg show error";
    return;
  }

  const name = document.getElementById("name").value.trim();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  const result = await registerUser({ name, email, password });
  if (!result.ok) {
    msgBox.textContent = result.error;
    msgBox.className = "form-msg show error";
    return;
  }

  msgBox.textContent = "Account created — redirecting…";
  msgBox.className = "form-msg show success";
  setTimeout(() => {
    location.href = getNextUrl("index.html");
  }, 500);
});

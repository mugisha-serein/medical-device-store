/* ============================================================
   Active Life Medical — Shared per-field form validation
   Used by the login, register, and checkout pages so every form
   gets the same live behavior: a field is validated once it has
   been blurred (touched), then re-validated on every keystroke
   so errors appear and clear as the user types. Empty fields are
   flagged live only once touched; untouched empty fields are
   caught by the submit-time pass (validateFields).
   Rules are maps of fieldId -> (value) => errorMessage or "".
   ============================================================ */

/* exported validateFields, attachLiveValidation, attachPasswordToggle */

/** Validates one field against its rule and toggles the wrapper's .has-error
 *  state. Returns the error message or "". skipEmpty avoids flagging required
 *  fields the user simply tabbed past. */
function validateField(fieldId, rules, { skipEmpty = false } = {}) {
  const input = document.getElementById(fieldId);
  const value = input ? String(input.value).trim() : "";
  const error = rules[fieldId] ? rules[fieldId](value) : "";
  const show = !!error && !(skipEmpty && !value);
  const wrapper = document.getElementById(`field-${fieldId}`);
  if (wrapper) wrapper.classList.toggle("has-error", show);
  return show ? error : "";
}

/** Validates every field in fieldIds; returns the list of error messages. */
function validateFields(fieldIds, rules) {
  return fieldIds.map(id => validateField(id, rules)).filter(Boolean);
}

/** Wires live blur/input feedback for every field in fieldIds. */
function attachLiveValidation(fieldIds, rules) {
  const touched = new Set();
  fieldIds.forEach(id => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener("blur", () => {
      touched.add(id);
      validateField(id, rules, { skipEmpty: true });
    });
    input.addEventListener("input", () => {
      if (touched.has(id)) validateField(id, rules);
    });
  });
}

/* ---- show/hide password toggles (login + register) ---- */

const EYE_ICON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12Z"/><circle cx="12" cy="12" r="3"/></svg>`;

const EYE_OFF_ICON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/></svg>`;

/** Wires a show/hide toggle to a password input. The toggle button sits inside
 *  a .password-wrap and swaps the input type plus the eye/eye-off icon. */
function attachPasswordToggle(inputId) {
  const input = document.getElementById(inputId);
  if (!input || !input.parentElement) return;
  const btn = input.parentElement.querySelector(".password-toggle");
  if (!btn) return;

  btn.innerHTML = EYE_ICON;
  btn.setAttribute("aria-pressed", "false");

  btn.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-pressed", String(show));
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    btn.innerHTML = show ? EYE_OFF_ICON : EYE_ICON;
  });
}

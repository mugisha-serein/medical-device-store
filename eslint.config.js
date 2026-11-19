import js from "@eslint/js";
import globals from "globals";

// ESLint 9 flat config for the Active Life Medical demo.
// The JS files are classic browser scripts sharing one global scope.
// Cross-file helpers are marked with `/* exported name */` in their defining
// file (so no-unused-vars ignores them) and with `/* global name */` in each
// consuming file (so no-undef passes) — e.g. `/* exported getCartDetailed */`
// in js/cart.js, `/* global getCartDetailed */` in js/pages/cart.js.
export default [
  {
    ignores: ["node_modules/**"],
  },
  js.configs.recommended,
  {
    files: ["js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser },
    },
    rules: {
      semi: ["error", "always"],
      quotes: ["error", "double", { avoidEscape: true, allowTemplateLiterals: true }],
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],
      "no-trailing-spaces": "error",
      "eol-last": ["error", "always"],
      "no-multi-spaces": "error",
    },
  },
  {
    // Node-side tooling: the smoke tests and the dev server.
    files: ["tests/**/*.mjs", "scripts/**/*.mjs", "eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: {
      semi: ["error", "always"],
      quotes: ["error", "double", { avoidEscape: true, allowTemplateLiterals: true }],
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "no-trailing-spaces": "error",
      "eol-last": ["error", "always"],
    },
  },
];

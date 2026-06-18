// ESLint flat config for the broadcast (stream) frontend.
//
// Mirrors web/eslint.config.js: bug-catching rules (hooks, `any`, unused
// symbols) are errors; stylistic / a11y nits are warnings so `eslint .`
// exits 0 today and stays useful as a CI gate going forward.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src-tauri", "*.config.js"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,

      // Errors that catch real bugs — keep strict.
      "react-hooks/rules-of-hooks": "error",
      "@typescript-eslint/no-explicit-any": "error",

      // The TS compiler already enforces no-unused via noUnusedLocals /
      // noUnusedParameters; mirror it here, allowing the conventional
      // underscore-prefix escape hatch for intentionally-unused symbols.
      "no-unused-vars": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],

      // Noisy / stylistic — keep as warnings so they surface without
      // failing the gate.
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-empty-object-type": "warn",
      "@typescript-eslint/no-unused-expressions": "warn",
      "no-empty": "warn",

      // jsx-a11y is aspirational here (full-screen broadcast canvas UI);
      // demote the whole set to warnings.
      "jsx-a11y/alt-text": "warn",
      "jsx-a11y/anchor-is-valid": "warn",
      "jsx-a11y/click-events-have-key-events": "warn",
      "jsx-a11y/no-static-element-interactions": "warn",
      "jsx-a11y/no-noninteractive-element-interactions": "warn",
      "jsx-a11y/label-has-associated-control": "warn",
      "jsx-a11y/media-has-caption": "warn",
      "jsx-a11y/no-autofocus": "warn",
    },
  },
);

import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default tseslint.config(
  // Union of both sides: ".vite" is Vite's dependency pre-bundle cache, which eslint was
  // linting and failing on rules that do not apply to generated code; "Refrence" is the
  // read-only research folder.
  { ignores: ["dist", "node_modules", "coverage", ".vite", "Refrence"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // Files that intentionally co-locate a component with non-component exports.
    files: [
      "src/main.tsx",
      "src/components/Shell.tsx",
      "src/hooks/useDashboardContext.tsx",
      "src/pages/dashboard/modules.tsx",
    ],
    rules: { "react-refresh/only-export-components": "off" },
  }
);

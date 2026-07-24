import js from "@eslint/js";

export default [
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        window: "readonly",
        document: "readonly",
        localStorage: "readonly",
        fetch: "readonly",
        URL: "readonly",
        console: "readonly",
        setTimeout: "readonly",
        clearInterval: "readonly",
        setInterval: "readonly",
        clearTimeout: "readonly",
        AbortController: "readonly",
        CustomEvent: "readonly",
        Event: "readonly",
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-undef": "error",
      "no-redeclare": "error",
      "no-constant-condition": "warn",
      "no-empty": "warn",
      eqeqeq: "warn",
      "no-debugger": "warn",
    },
  },
  {
    ignores: ["dist/**", "node_modules/**", "vite.config.js", "tailwind.config.js"],
  },
];

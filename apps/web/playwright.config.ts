import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: { baseURL: "http://localhost:4174" },
  webServer: {
    command: "npx serve out -l 4174 --no-clipboard",
    port: 4174,
    reuseExistingServer: true,
  },
});

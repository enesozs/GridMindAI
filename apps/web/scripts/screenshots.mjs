// Capture screenshots of the built static site (out/) in light and dark mode.
// Usage: node scripts/screenshots.mjs [outDir]   (run `npm run build` first)
import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";

const outDir = process.argv[2] ?? "../../docs/screenshots";
const PORT = 4173;
const pages = [
  ["atlas", "/"],
  ["forecast", "/forecast/"],
  ["models", "/models/"],
  ["track-record", "/track-record/"],
  ["renewables", "/renewables/"],
  ["storage", "/storage/"],
  ["methods", "/methods/"],
];

mkdirSync(outDir, { recursive: true });
const server = spawn("npx", ["serve", "out", "-l", String(PORT), "--no-clipboard"], { stdio: "ignore" });
await new Promise((r) => setTimeout(r, 2500));
const browser = await chromium.launch();
const errors = [];
try {
  for (const scheme of ["light", "dark"]) {
    for (const width of [1440, 390]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      page.on("console", (m) => m.type() === "error" && errors.push(`${scheme} ${width}: ${m.text()}`));
      page.on("pageerror", (e) => errors.push(`${scheme} ${width}: ${e.message}`));
      for (const [name, path] of pages) {
        await page.goto(`http://localhost:${PORT}${path}`, { waitUntil: "networkidle" });
        await page.waitForTimeout(1200); // let charts finish their entry animation
        const suffix = width < 600 ? "-mobile" : "";
        await page.screenshot({ path: `${outDir}/${name}-${scheme}${suffix}.png`, fullPage: true });
      }
      await ctx.close();
    }
  }
} finally {
  await browser.close();
  server.kill();
}
if (errors.length) {
  console.error("Console errors:\n" + errors.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`screenshots written to ${outDir}`);
}

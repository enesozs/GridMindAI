import { expect, test } from "@playwright/test";

// Smoke checks on the critical paths of the static build (run `npm run build` first).

test("atlas renders map, charts and source attribution", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Energy Atlas" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Map of German TSO control areas/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /Heatmap of hourly load/ })).toBeVisible();
  await expect(page.getByText("Bundesnetzagentur | SMARD.de").first()).toBeVisible();
  // Default day is a complete day: the headline card shows a GW value, not a dash.
  await expect(page.getByText(/^\d+\.\d GW$/).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("forecast studio shows issue time and both forecasts", async ({ page }) => {
  await page.goto("/forecast/");
  await expect(page.getByRole("heading", { name: "Forecast Studio" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Forecast fan chart/ })).toBeVisible();
  await expect(page.getByText("Issued at (local)")).toBeVisible();
  await page.getByRole("button", { name: "Previous day" }).click();
  await expect(page.getByText(/Delivery day \d{4}-\d{2}-\d{2}/)).toBeVisible();
});

test("model lab lists the TSO benchmark", async ({ page }) => {
  await page.goto("/models/");
  await expect(page.getByRole("cell", { name: "TSO official forecast" }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: /GridMind GBM \+ weather/ }).first()).toBeVisible();
});

test("theme toggle switches to dark", async ({ page }) => {
  await page.goto("/methods/");
  const btn = page.getByRole("button", { name: /Theme:/ });
  await btn.click(); // system -> light
  await btn.click(); // light -> dark
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("renewables page shows the TSO benchmark per technology", async ({ page }) => {
  await page.goto("/renewables/");
  await expect(page.getByRole("heading", { name: "Renewables" })).toBeVisible();
  await expect(page.getByRole("cell", { name: /TSO day-ahead forecast/ })).toBeVisible();
  await page.getByRole("tab", { name: "Wind onshore" }).click();
  await expect(page.getByRole("img", { name: /Wind onshore forecast/ })).toBeVisible();
});

test("storage lab shows value captured and dispatch for a day", async ({ page }) => {
  await page.goto("/storage/");
  await expect(page.getByRole("heading", { name: "Storage Lab" })).toBeVisible();
  await expect(page.getByRole("cell", { name: /Perfect foresight/ })).toBeVisible();
  await expect(page.getByRole("img", { name: /Storage dispatch and state of charge/ })).toBeVisible();
  await page.getByRole("combobox").selectOption("tso");
  await expect(page.getByRole("img", { name: /Residual load with storage/ })).toBeVisible();
});

test("atlas shows control-area forecasts and the skill map mode", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Control-area forecasts" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "TenneT" })).toBeVisible();
  await page.getByRole("button", { name: /forecast skill vs TSO/ }).click();
  await expect(page.getByRole("img", { name: /coloured by skill/ })).toBeVisible();
  await page.getByLabel("Control area", { exact: true }).selectOption("DE_AMPRION");
  await expect(page.getByRole("img", { name: /Amprion day-ahead load forecast/ })).toBeVisible();
});

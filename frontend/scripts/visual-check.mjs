import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const baseUrl = process.env.SIGNALFORGE_UI_URL ?? "http://127.0.0.1:5173";
const executablePath =
  process.env.PLAYWRIGHT_BROWSER_PATH ??
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const outputDir = fileURLToPath(new URL("../test-results/", import.meta.url));
const allRoutes = [
  { name: "overview", path: "/" },
  { name: "decisions", path: "/decisions" },
  { name: "positions", path: "/positions" },
  { name: "history", path: "/history" },
  { name: "scanner", path: "/scanner" },
  { name: "risk", path: "/risk" },
  { name: "configuration", path: "/configuration" },
];
const routeFilter = process.env.SIGNALFORGE_VISUAL_ROUTE;
const routes = routeFilter
  ? allRoutes.filter((route) => route.name === routeFilter)
  : allRoutes;

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const results = [];

for (const viewport of [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
]) {
  for (const route of routes) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));

    await page.goto(`${baseUrl}${route.path}`, { waitUntil: "domcontentloaded" });
    await page.locator("h1").waitFor({ timeout: 30_000 });
    let tokenDialogOpened = null;
    let scannerRows = null;
    if (route.name === "overview") {
      const scanButton = page.getByTitle("Run one scan");
      if (await scanButton.isEnabled()) {
        await scanButton.click();
        await page.locator('[role="dialog"]').waitFor();
        tokenDialogOpened = await page.locator('[role="dialog"]').isVisible();
        await page.getByRole("button", { name: "Cancel" }).click();
      }
    }
    if (route.name === "scanner") {
      const responsePromise = page.waitForResponse(
        (response) => response.url().includes("/api/v1/market/opportunities"),
        { timeout: 90_000 },
      );
      await page.getByRole("button", { name: "Scan market" }).click();
      await responsePromise;
      await page.locator("tbody tr").first().waitFor({ timeout: 30_000 });
      scannerRows = await page.locator("tbody tr").count();
    }
    await page.screenshot({
      path: `${outputDir}${viewport.name}-${route.name}.png`,
      fullPage: true,
    });

    const layout = await page.evaluate(() => ({
      title: document.title,
      heading: document.querySelector("h1")?.textContent ?? null,
      textLength: document.body.innerText.trim().length,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      viewportWidth: window.innerWidth,
      contentWidth: document.documentElement.scrollWidth,
    }));
    results.push({
      viewport: viewport.name,
      route: route.name,
      tokenDialogOpened,
      scannerRows,
      ...layout,
      errors,
    });
    await page.close();
  }
}

await browser.close();
console.log(JSON.stringify(results, null, 2));

if (
  results.some(
    (result) => result.errors.length || result.horizontalOverflow || result.textLength < 100,
  )
) {
  process.exitCode = 1;
}

import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "C:/Users/Rituraj/Desktop/dark-mode-check-v2";
fs.mkdirSync(OUT, { recursive: true });

const PAGES = [
  ["trace-49", "/trace/49"],
  ["trace-47", "/trace/47"],
  ["inbox", "/inbox"],
  ["hitl", "/hitl"],
  ["learning", "/learning"],
  ["kb-intent", "/kb?ns=intent"],
  ["analytics", "/analytics"],
  ["data-customers", "/data?tab=customers"],
];

const SUFFIX = process.argv[2] || "after";
const MODE = process.argv[3] || "both"; // "dark" | "light" | "both"

async function capture(mode, suffix) {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1100 },
    deviceScaleFactor: 1,
  });
  // Pre-set localStorage by visiting once + adding init script
  await context.addInitScript((m) => {
    try { localStorage.setItem("zbrain.theme", m); } catch (e) {}
    if (m === "dark") {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, mode);

  for (const [name, route] of PAGES) {
    const page = await context.newPage();
    const url = BASE + route;
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      // give the app a moment to render data + apply theme
      await page.waitForTimeout(3500);
      // Force a final theme reapplication just in case React's effect ran later
      await page.evaluate((m) => {
        try { localStorage.setItem("zbrain.theme", m); } catch (e) {}
        document.documentElement.classList.toggle("dark", m === "dark");
      }, mode);
      await page.waitForTimeout(400);
      const file = path.join(OUT, `${name}-${mode}-${suffix}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log("WROTE", file);
    } catch (e) {
      console.error("FAIL", name, e.message);
    } finally {
      await page.close();
    }
  }

  await context.close();
  await browser.close();
}

(async () => {
  if (MODE === "both" || MODE === "dark") await capture("dark", SUFFIX);
  if (MODE === "both" || MODE === "light") await capture("light", SUFFIX);
  console.log("DONE");
})();

import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";

const BASE = "http://localhost:5173";
const OUT = "C:/Users/Rituraj/Desktop/dark-mode-check-v2";
fs.mkdirSync(OUT, { recursive: true });

const SUFFIX = process.argv[2] || "before";

async function withBrowser(mode, fn) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  await context.addInitScript((m) => {
    try { localStorage.setItem("zbrain.theme", m); } catch (e) {}
    document.documentElement.classList.toggle("dark", m === "dark");
  }, mode);
  try {
    await fn(context);
  } finally {
    await context.close();
    await browser.close();
  }
}

async function shoot(page, name, mode) {
  await page.waitForTimeout(800);
  await page.evaluate((m) => {
    try { localStorage.setItem("zbrain.theme", m); } catch (e) {}
    document.documentElement.classList.toggle("dark", m === "dark");
  }, mode);
  await page.waitForTimeout(300);
  const file = path.join(OUT, `${name}-${mode}-${SUFFIX}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log("WROTE", file);
}

for (const mode of ["dark", "light"]) {
  await withBrowser(mode, async (ctx) => {
    // Trace 49 — click "Show full message" + click into "Decide" stage + expand a sub-step
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/trace/49", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      // Try clicking "Show full message" if present
      try {
        const sfm = page.locator("text=/Show full message/i").first();
        if (await sfm.count()) await sfm.click({ timeout: 1000 });
      } catch (e) {}
      // Click Decide stage card if available
      try {
        const dec = page.locator("text=/Decision .* Confidence/i").first();
        if (await dec.count()) await dec.click({ timeout: 1000 });
      } catch (e) {}
      await page.waitForTimeout(700);
      // Try clicking "Agent toolbelt" expand
      try {
        const tb = page.locator("text=/Agent toolbelt/i").first();
        if (await tb.count()) await tb.click({ timeout: 1000 });
      } catch (e) {}
      // Try clicking Raw JSON
      try {
        const raw = page.locator("text=/^Raw JSON$/").first();
        if (await raw.count()) await raw.click({ timeout: 1000 });
      } catch (e) {}
      await page.waitForTimeout(500);
      await shoot(page, "trace-49-decide-expanded", mode);
      await page.close();
    }

    // HITL — click first task to open detail
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/hitl", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      try {
        // Click the first task card on the left
        const firstTask = page.locator("text=/Reschedule shipment|Quick: WO|Convert quote|修理依頼|Solicitud|Q2O/i").first();
        if (await firstTask.count()) await firstTask.click({ timeout: 1500 });
      } catch (e) {}
      await page.waitForTimeout(800);
      await shoot(page, "hitl-detail", mode);
      await page.close();
    }

    // Inbox — click first email
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/inbox", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      try {
        const view = page.locator("text=/View activity/i").first();
        if (await view.count()) await view.click({ timeout: 1500 });
        await page.waitForTimeout(2500);
      } catch (e) {}
      await shoot(page, "inbox-after-click", mode);
      await page.close();
    }

    // Data — quotes tab (different layout)
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/data?tab=quotes", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      await shoot(page, "data-quotes", mode);
      await page.close();
    }

    // KB — extraction-schema tab
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/kb?ns=extract", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      await shoot(page, "kb-extract", mode);
      await page.close();
    }

    // Settings page
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/settings", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      await shoot(page, "settings", mode);
      await page.close();
    }

    // FeedbackLog
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/feedback", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      await shoot(page, "feedback", mode);
      await page.close();
    }

    // Customer detail modal — open from data table
    {
      const page = await ctx.newPage();
      await page.goto(BASE + "/data?tab=customers", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3500);
      try {
        // Click a customer row
        const row = page.locator("text=/Aurora Automotive Electronics/").first();
        if (await row.count()) await row.click({ timeout: 1500 });
        await page.waitForTimeout(1500);
      } catch (e) {}
      await shoot(page, "customer-modal", mode);
      await page.close();
    }
  });
}
console.log("DONE");

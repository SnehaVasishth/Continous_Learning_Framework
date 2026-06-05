/**
 * record.mjs — Records one .webm clip per scene defined in tour.json.
 *
 *   DEMO_BASE_URL=https://app.solution.example.com node record.mjs
 *
 * Per scene: launches an isolated browser context with video recording on,
 * navigates to BASE_URL + scene.path, runs optional actions, waits settleMs,
 * then closes the context (which finalizes the .webm).
 *
 * Actions supported:
 *   { type: "wait",       ms }
 *   { type: "scroll",     deltaY }                     // mousewheel-style
 *   { type: "scrollTo",   y }                          // absolute scroll position (smooth)
 *   { type: "hoverFirst", selector }
 *   { type: "hoverText",  text }                       // hover first element whose innerText matches
 *   { type: "click",      selector }
 *   { type: "clickText",  text }                       // click first element whose innerText matches
 *
 * Per-context tweaks vs vanilla Playwright:
 *   1. setInterval timers with ms > 500 are nuked after a startup grace
 *      window so polling does not refresh the page during recording.
 *   2. A visible cursor element follows native mouse events so hovers and
 *      clicks read as human motion in the final video.
 *   3. Caret, scrollbar, and focus ring are hidden via injected CSS.
 */
import { chromium } from "playwright";
import { readFile, mkdir, rename, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TOUR_PATH = path.join(__dirname, "tour.json");
const OUT_DIR = path.join(__dirname, "out");
const CLIP_DIR = path.join(OUT_DIR, "clips");

const BASE_URL = process.env.DEMO_BASE_URL;
if (!BASE_URL) {
  console.error("ERROR: DEMO_BASE_URL is not set.");
  console.error('Example: DEMO_BASE_URL="https://app.solution.example.com" node record.mjs');
  process.exit(1);
}

const tour = JSON.parse(await readFile(TOUR_PATH, "utf8"));
const { width, height, fps } = tour.video;

await mkdir(CLIP_DIR, { recursive: true });

// Script injected before every page navigation. Four jobs:
//   - Freeze long-running setInterval timers: track every poll registered
//     during the grace window, then clear them all when grace ends. Any new
//     poll after grace is dropped at registration time.
//   - Disable EventSource so Server-Sent Events streams cannot keep
//     re-rendering the page mid-scene (e.g. /api/trace/stream).
//   - Mount a macOS-style arrow cursor that tracks native mouse events with
//     a click ripple. Playwright drives the real mouse; this is the visible
//     overlay so the viewer can SEE hovers and clicks happen.
//   - Hide caret, scrollbar, and focus rings.
const INIT_SCRIPT = `
(function () {
  const GRACE_MS = 3500;
  const POLL_MS  = 600;

  // --- (1) Polling freeze.
  const realSetInterval   = window.setInterval.bind(window);
  const realClearInterval = window.clearInterval.bind(window);
  const tracked = new Set();
  // During grace: register normally but track every poll-interval id.
  window.setInterval = function (handler, period, ...rest) {
    const id = realSetInterval(handler, period, ...rest);
    if (typeof period === "number" && period >= POLL_MS) tracked.add(id);
    return id;
  };
  setTimeout(() => {
    // Clear everything we tracked.
    tracked.forEach((id) => { try { realClearInterval(id); } catch (e) {} });
    tracked.clear();
    // From now on, drop any new poll-interval registration outright.
    window.setInterval = function (handler, period, ...rest) {
      if (typeof period === "number" && period >= POLL_MS) return -1;
      return realSetInterval(handler, period, ...rest);
    };
  }, GRACE_MS);

  // --- (2) Disable EventSource (SSE) entirely. Pipelines we record are
  //         always in a terminal state so we never need live events.
  const NoopES = function (url) {
    return {
      url: String(url || ""),
      readyState: 2, // CLOSED
      withCredentials: false,
      onopen: null, onmessage: null, onerror: null,
      addEventListener() {}, removeEventListener() {},
      dispatchEvent() { return true; },
      close() {},
    };
  };
  NoopES.CONNECTING = 0; NoopES.OPEN = 1; NoopES.CLOSED = 2;
  try { window.EventSource = NoopES; } catch (e) {}

  // --- (3) Visible cursor. Classic mouse pointer SVG with a click ripple.
  //         Hotspot (the tip) sits at the (x, y) of native mousemove.
  const installCursor = () => {
    if (document.getElementById("__demo-cursor")) return;
    const cursor = document.createElement("div");
    cursor.id = "__demo-cursor";
    cursor.innerHTML = [
      '<svg width="22" height="22" viewBox="0 0 32 32"',
      ' xmlns="http://www.w3.org/2000/svg"',
      ' style="filter: drop-shadow(0 1px 2px rgba(0,0,0,0.35));">',
        '<path',
          ' d="M5 3 L5 23 L11 18 L14 24 L18 22 L15 16 L23 16 Z"',
          ' fill="#111827"',
          ' stroke="#FFFFFF"',
          ' stroke-width="1.8"',
          ' stroke-linejoin="round"',
          ' stroke-linecap="round" />',
      '</svg>',
    ].join("");
    cursor.style.cssText = [
      "position:fixed",
      "top:0","left:0",
      "width:22px","height:22px",
      "pointer-events:none",
      "z-index:2147483647",
      // Anchor the SVG so its visual TIP (svg coord 5,3 -> px 3.4, 2.1) lands at the mouse position.
      "margin-left:-3.4px","margin-top:-2.1px",
      "will-change:left,top",
    ].join(";");
    document.body.appendChild(cursor);

    const move = (x, y) => {
      cursor.style.left = x + "px";
      cursor.style.top  = y + "px";
    };
    window.addEventListener("mousemove", (e) => move(e.clientX, e.clientY), { capture: true, passive: true });
    window.addEventListener("mousedown", (e) => {
      // Spawn a brief ring centered on the click point.
      const r = document.createElement("div");
      r.style.cssText = [
        "position:fixed",
        "left:" + e.clientX + "px","top:" + e.clientY + "px",
        "width:14px","height:14px",
        "border-radius:50%",
        "border:2px solid rgba(26,85,249,0.95)",
        "background:rgba(26,85,249,0.18)",
        "pointer-events:none",
        "z-index:2147483646",
        "transform:translate(-50%,-50%) scale(1)",
        "opacity:1",
        "transition:transform 0.55s cubic-bezier(0.16,0.84,0.44,1), opacity 0.55s ease-out",
      ].join(";");
      document.body.appendChild(r);
      requestAnimationFrame(() => {
        r.style.transform = "translate(-50%,-50%) scale(3.4)";
        r.style.opacity = "0";
      });
      setTimeout(() => r.remove(), 620);
    }, { capture: true });

    move(window.innerWidth / 2, window.innerHeight / 2);
  };
  if (document.body) installCursor();
  else document.addEventListener("DOMContentLoaded", installCursor);

  // --- (4) Cosmetic cleanup.
  const css = document.createElement("style");
  css.textContent = [
    "*::-webkit-scrollbar { display: none !important; }",
    "body { caret-color: transparent !important; }",
    "*:focus, *:focus-visible { outline: none !important; box-shadow: none !important; }",
    // Hide the real OS cursor so only the injected one is visible. (Playwright
    // doesn't render the host cursor in screen capture but this is defensive
    // against any focused input that might reveal a text caret.)
    "html, body, * { cursor: none !important; }",
  ].join("\\n");
  (document.head || document.documentElement).appendChild(css);
})();
`;

// Smooth mouse motion. Playwright's mouse.move() supports a `steps` param
// but a per-step delay produces a slower glide that reads as human.
// We track the last cursor position across calls so each glide starts where
// the previous one ended.
let __lastCursor = { x: width / 2, y: height / 2 };
async function glideTo(page, x, y, { steps = 18, stepDelay = 14 } = {}) {
  const start = __lastCursor;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // Ease-in-out cubic for natural motion.
    const ease = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    const mx = start.x + (x - start.x) * ease;
    const my = start.y + (y - start.y) * ease;
    await page.mouse.move(mx, my);
    await page.waitForTimeout(stepDelay);
  }
  __lastCursor = { x, y };
}

function resetCursor() {
  __lastCursor = { x: width / 2, y: height / 2 };
}

async function elementCenter(page, selectorOrLocator) {
  const loc = typeof selectorOrLocator === "string"
    ? page.locator(selectorOrLocator).first()
    : selectorOrLocator;
  await loc.waitFor({ state: "visible", timeout: 5000 });
  await loc.scrollIntoViewIfNeeded().catch(() => {});
  const box = await loc.boundingBox();
  if (!box) throw new Error("no bounding box for target");
  return { loc, x: box.x + box.width / 2, y: box.y + Math.min(box.height / 2, 36) };
}

async function locateByText(page, text) {
  // Prefer interactive elements (button, a, [role=button], NavLink). Falls
  // back to any visible element. Case-sensitive substring match.
  const candidates = [
    `button:has-text("${text}")`,
    `a:has-text("${text}")`,
    `[role="button"]:has-text("${text}")`,
    `[role="tab"]:has-text("${text}")`,
    `:text("${text}")`,
  ];
  for (const sel of candidates) {
    const loc = page.locator(sel).first();
    if (await loc.count().catch(() => 0)) {
      try {
        await loc.waitFor({ state: "visible", timeout: 1500 });
        return loc;
      } catch { /* try next */ }
    }
  }
  throw new Error(`no visible element matches text "${text}"`);
}

const browser = await chromium.launch({
  headless: true,
  args: ["--disable-blink-features=AutomationControlled"],
});

let recorded = 0;
for (const scene of tour.scenes) {
  const sceneTmpDir = path.join(CLIP_DIR, `_tmp_${scene.id}`);
  const finalPath = path.join(CLIP_DIR, `${scene.id}.webm`);

  if (existsSync(finalPath)) await rm(finalPath);
  await rm(sceneTmpDir, { recursive: true, force: true });
  await mkdir(sceneTmpDir, { recursive: true });

  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 2,
    recordVideo: { dir: sceneTmpDir, size: { width, height } },
    ignoreHTTPSErrors: true,
  });
  await context.addInitScript(INIT_SCRIPT);
  const page = await context.newPage();
  resetCursor();

  const url = new URL(scene.path.replace(/^\//, ""), BASE_URL + (BASE_URL.endsWith("/") ? "" : "/")).toString();
  console.log(`[${scene.id}] -> ${url}`);

  try {
    // Pages with live polling never reach networkidle. Try briefly, then
    // fall back to domcontentloaded.
    await page.goto(url, { waitUntil: "networkidle", timeout: 5_000 }).catch(async () => {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15_000 });
    });
  } catch (err) {
    console.error(`[${scene.id}] navigation failed: ${err.message}`);
  }

  // Initial settle so React has time to mount, fonts to load, and any
  // first-paint flicker to finish before we start interacting.
  await page.waitForTimeout(scene.preActionsMs ?? 800);

  // Run actions.
  for (const action of scene.actions ?? []) {
    try {
      if (action.type === "wait") {
        await page.waitForTimeout(action.ms ?? 500);
      } else if (action.type === "scroll") {
        await page.mouse.wheel(0, action.deltaY ?? 400);
      } else if (action.type === "scrollTo") {
        await page.evaluate((y) => window.scrollTo({ top: y, behavior: "smooth" }), action.y ?? 0);
      } else if (action.type === "hoverFirst" && action.selector) {
        const { x, y } = await elementCenter(page, action.selector);
        await glideTo(page, x, y);
      } else if (action.type === "hoverText" && action.text) {
        const loc = await locateByText(page, action.text);
        const { x, y } = await elementCenter(page, loc);
        await glideTo(page, x, y);
      } else if (action.type === "click" && action.selector) {
        const { loc, x, y } = await elementCenter(page, action.selector);
        await glideTo(page, x, y);
        await page.waitForTimeout(180);
        await loc.click({ delay: 80 });
      } else if (action.type === "clickText" && action.text) {
        const loc = await locateByText(page, action.text);
        const { x, y } = await elementCenter(page, loc);
        await glideTo(page, x, y);
        await page.waitForTimeout(180);
        await loc.click({ delay: 80 });
      }
    } catch (err) {
      console.warn(`[${scene.id}] action ${action.type} skipped: ${err.message}`);
    }
  }

  await page.waitForTimeout(scene.settleMs ?? 1500);

  const video = page.video();
  await context.close();
  if (video) {
    const tmpPath = await video.path();
    await rename(tmpPath, finalPath);
    console.log(`[${scene.id}] saved ${path.relative(__dirname, finalPath)}`);
    recorded += 1;
  }
  await rm(sceneTmpDir, { recursive: true, force: true });
}

await browser.close();
console.log(`\nDone. Recorded ${recorded}/${tour.scenes.length} clips at ${fps}fps ${width}x${height}.`);

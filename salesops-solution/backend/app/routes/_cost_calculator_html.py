"""Interactive cost calculator HTML, served verbatim at
/api/docs/rfp-reply/cost-calculator. Pure HTML + vanilla JS so it does not
depend on the Vite bundle and renders cleanly inside the RFP-reply viewer."""

COST_CALCULATOR_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Cost Calculator · Keysight RFP Response · ZBrain</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    --ink: #131426; --muted: #6B7280; --rule: #E5E7EB; --surface: #F8FAFC;
    --accent: #1A55F9; --accent-soft: #1A55F910; --ok: #1F8A4C; --warn: #C77700;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, Inter, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 0; background: var(--surface); color: var(--ink);
         line-height: 1.55; }
  .shell { max-width: 1400px; margin: 0 auto; padding: 28px 24px 64px; }
  header { margin-bottom: 24px; }
  .eyebrow { font-size: 11px; font-weight: 700; color: var(--accent);
             letter-spacing: 0.14em; text-transform: uppercase; }
  h1 { font-size: 26px; font-weight: 700; margin: 6px 0 2px; letter-spacing: -0.02em; }
  .sub { color: #374151; font-size: 14px; max-width: 900px; }
  .grid { display: grid; grid-template-columns: 1fr 1.4fr; gap: 24px; }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
  .card { background: white; border: 1px solid var(--rule); border-radius: 12px;
          padding: 20px 22px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }
  .card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.12em;
             color: var(--muted); margin: 0 0 4px; font-weight: 700; }
  .card h2.l { font-size: 16px; text-transform: none; letter-spacing: -0.01em;
               color: var(--ink); font-weight: 700; margin-top: 0; }
  .field { display: flex; align-items: center; justify-content: space-between;
           padding: 9px 0; border-bottom: 1px dashed var(--rule); gap: 12px; }
  .field:last-child { border-bottom: none; }
  .field label { font-size: 13px; color: var(--ink); flex: 1 1 auto;
                 max-width: 70%; line-height: 1.35; }
  .field .help { display: block; font-size: 11px; color: var(--muted); margin-top: 2px; }
  .field input { width: 130px; padding: 6px 10px; border: 1px solid var(--rule);
                 border-radius: 6px; font-size: 13px; text-align: right;
                 font-variant-numeric: tabular-nums; font-family: inherit;
                 background: white; color: var(--ink); }
  .field input:focus { outline: none; border-color: var(--accent);
                       box-shadow: 0 0 0 3px var(--accent-soft); }
  .field select { width: 200px; padding: 6px 10px; border: 1px solid var(--rule);
                  border-radius: 6px; font-size: 13px; background: white;
                  font-family: inherit; color: var(--ink); }
  .section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em;
                   color: var(--muted); margin: 18px 0 6px; font-weight: 700; }
  .section-title:first-child { margin-top: 0; }
  .btn-row { display: flex; gap: 8px; margin-top: 14px; }
  .btn { font-size: 12px; padding: 7px 14px; border-radius: 6px;
         border: 1px solid var(--rule); background: white; color: var(--ink);
         cursor: pointer; font-family: inherit; font-weight: 500; }
  .btn:hover { background: var(--surface); }
  .btn.primary { background: var(--accent); color: white; border-color: var(--accent); }
  .btn.primary:hover { opacity: 0.9; }
  .totals { display: grid; grid-template-columns: 1fr 1fr 1fr;
            gap: 12px; margin-bottom: 16px; }
  .total { background: var(--surface); border: 1px solid var(--rule);
           border-radius: 10px; padding: 14px 16px; }
  .total .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em;
                color: var(--muted); font-weight: 700; }
  .total .val { font-size: 26px; font-weight: 700; color: var(--ink);
                font-variant-numeric: tabular-nums; margin-top: 6px;
                letter-spacing: -0.02em; }
  .total .sub { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .total.big .val { color: var(--accent); font-size: 32px; }
  .breakdown { margin-top: 8px; }
  .row { display: grid; grid-template-columns: 1fr 100px 70px;
         padding: 9px 0; border-bottom: 1px solid var(--rule);
         font-size: 13px; align-items: center; gap: 12px; }
  .row:last-child { border-bottom: none; }
  .row .lbl { color: var(--ink); }
  .row .lbl .h { display: block; color: var(--muted); font-size: 11px;
                 margin-top: 1px; }
  .row .v { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
  .row .p { text-align: right; color: var(--muted); font-size: 11px;
            font-variant-numeric: tabular-nums; }
  .stage-row { display: grid; grid-template-columns: 1fr 120px 70px; }
  .bar { height: 6px; background: var(--surface); border-radius: 3px;
         overflow: hidden; margin-top: 4px; }
  .bar > i { display: block; height: 100%; background: var(--accent); }
  .note { background: var(--accent-soft); border-left: 3px solid var(--accent);
          padding: 10px 14px; border-radius: 6px; font-size: 12px;
          color: #1F2937; margin-top: 12px; }
  .note b { color: var(--ink); }
  .footer { font-size: 11px; color: var(--muted); margin-top: 24px;
            line-height: 1.6; }
  .footer code { background: var(--surface); padding: 1px 5px; border-radius: 3px; }
</style>
</head>
<body>
<div class="shell">

<header>
  <div class="eyebrow">Keysight RFP Response · Pricing model</div>
  <h1>Cost calculator</h1>
  <p class="sub">
    Live cost projection anchored to the stated 880k annual email baseline (about
    2,000 per day). Every assumption is editable; totals recompute instantly. The
    model splits cost into Azure Document Intelligence OCR, Azure OpenAI input
    tokens, Azure OpenAI output tokens, and translation, across the six processing
    stages.
  </p>
</header>

<div class="grid">

  <!-- ============== INPUTS ============== -->
  <div class="card">
    <h2 class="l">Inputs · editable</h2>

    <div class="section-title">Volume</div>
    <div class="field">
      <label>Annual inbound emails<span class="help">Per Keysight Q&A baseline (~2k/day)</span></label>
      <input type="number" id="emailsPerYear" value="880000" min="0" step="10000" />
    </div>
    <div class="field">
      <label>Average attachments per email<span class="help">Working assumption, refined at Functional Design</span></label>
      <input type="number" id="attachPerEmail" value="5" min="0" step="0.1" />
    </div>
    <div class="field">
      <label>Average pages per attachment<span class="help">Mix of PO PDFs, scans, embedded items</span></label>
      <input type="number" id="pagesPerAttachment" value="10" min="0" step="0.5" />
    </div>
    <div class="field">
      <label>Average email body size (KB)<span class="help">Body text after stripping signatures</span></label>
      <input type="number" id="bodyKb" value="6" min="0" step="0.5" />
    </div>

    <div class="section-title">LLM token mix (per email)</div>
    <div class="field">
      <label>Intake classification — input tokens<span class="help">Email body + top of thread, two-pass classifier</span></label>
      <input type="number" id="classifyIn" value="1100" min="0" step="50" />
    </div>
    <div class="field">
      <label>Intake classification — output tokens</label>
      <input type="number" id="classifyOut" value="180" min="0" step="10" />
    </div>
    <div class="field">
      <label>% of pages that get LLM extraction<span class="help">PO-relevant pages only, not full attachment</span></label>
      <input type="number" id="extractPagePct" value="35" min="0" max="100" step="1" />
    </div>
    <div class="field">
      <label>Per-page extraction — input tokens<span class="help">OCR text + per-intent schema prompt</span></label>
      <input type="number" id="extractInPerPage" value="1500" min="0" step="50" />
    </div>
    <div class="field">
      <label>Per-page extraction — output tokens<span class="help">Structured JSON of extracted fields</span></label>
      <input type="number" id="extractOutPerPage" value="600" min="0" step="50" />
    </div>
    <div class="field">
      <label>Decision call — input tokens<span class="help">Context + four-gate scoring prompt</span></label>
      <input type="number" id="decideIn" value="800" min="0" step="50" />
    </div>
    <div class="field">
      <label>Decision call — output tokens</label>
      <input type="number" id="decideOut" value="200" min="0" step="10" />
    </div>
    <div class="field">
      <label>Reply drafting — input tokens<span class="help">Resolved entities + reply template + glossary</span></label>
      <input type="number" id="replyIn" value="1500" min="0" step="50" />
    </div>
    <div class="field">
      <label>Reply drafting — output tokens<span class="help">Customer-facing reply body</span></label>
      <input type="number" id="replyOut" value="500" min="0" step="10" />
    </div>

    <div class="section-title">Translation</div>
    <div class="field">
      <label>% of emails requiring translation<span class="help">Non-English inbound + outbound reply</span></label>
      <input type="number" id="translatePct" value="25" min="0" max="100" step="1" />
    </div>
    <div class="field">
      <label>Avg characters per translation pass<span class="help">Body + reply, both directions when needed</span></label>
      <input type="number" id="translateChars" value="1800" min="0" step="100" />
    </div>

    <div class="section-title">Unit prices (USD)</div>
    <div class="field">
      <label>LLM family<span class="help">Switches input, cached-input, and output unit prices</span></label>
      <select id="llmFamily">
        <option value="gpt54" selected>GPT-5.4</option>
        <option value="gpt54mini">GPT-5.4 mini</option>
        <option value="gpt54nano">GPT-5.4 nano</option>
        <option value="gpt54pro">GPT-5.4 pro</option>
        <option value="gpt55">GPT-5.5</option>
        <option value="gpt55pro">GPT-5.5 pro</option>
        <option value="custom">Custom</option>
      </select>
    </div>
    <div class="field">
      <label>LLM input · $ per 1M tokens</label>
      <input type="number" id="llmInPrice" value="2.50" min="0" step="0.05" />
    </div>
    <div class="field">
      <label>LLM cached input · $ per 1M tokens<span class="help">Used when system + glossary prompts are re-fetched from cache</span></label>
      <input type="number" id="llmCachedPrice" value="0.25" min="0" step="0.01" />
    </div>
    <div class="field">
      <label>% of input tokens hitting prompt cache<span class="help">Repeated system prompt + KB exemplars</span></label>
      <input type="number" id="cachedPct" value="50" min="0" max="100" step="1" />
    </div>
    <div class="field">
      <label>LLM output · $ per 1M tokens</label>
      <input type="number" id="llmOutPrice" value="15.00" min="0" step="0.05" />
    </div>
    <div class="field">
      <label>Azure DI model<span class="help">Pricing from prices.azure.com retail API (S0 pay-as-you-go)</span></label>
      <select id="ocrModel">
        <option value="read" selected>Read (basic OCR text) · $1.50 / 1k pages</option>
        <option value="layout">Layout (structure-aware) · $10.00 / 1k pages</option>
        <option value="prebuilt">Prebuilt (invoice, receipt, ID) · $10.00 / 1k pages</option>
        <option value="custom">Custom extraction · $30.00 / 1k pages</option>
        <option value="custom_gen">Custom generative · $30.00 / 1k pages</option>
        <option value="classifier">Document classifier · $3.00 / 1k pages</option>
        <option value="custom_model">Custom (set price below)</option>
      </select>
    </div>
    <div class="field">
      <label>Azure DI · $ per 1k pages</label>
      <input type="number" id="ocrPrice" value="1.50" min="0" step="0.05" />
    </div>
    <div class="field">
      <label>Translation · $ per 1M characters<span class="help">Azure Translator standard tier</span></label>
      <input type="number" id="translatePrice" value="10.00" min="0" step="0.5" />
    </div>

    <div class="btn-row">
      <button class="btn primary" onclick="resetDefaults()">Reset to defaults</button>
      <button class="btn" onclick="copyShareLink()">Copy share link</button>
    </div>
  </div>

  <!-- ============== OUTPUTS ============== -->
  <div class="card">
    <h2 class="l">Projected cost</h2>

    <div class="totals">
      <div class="total big">
        <div class="lbl">Annual total</div>
        <div class="val" id="annualTotal">$0</div>
        <div class="sub" id="annualPerEmail">$0.00 per email</div>
      </div>
      <div class="total">
        <div class="lbl">Monthly</div>
        <div class="val" id="monthlyTotal">$0</div>
        <div class="sub" id="monthlyVol">0 emails / month</div>
      </div>
      <div class="total">
        <div class="lbl">Per case</div>
        <div class="val" id="perCase">$0</div>
        <div class="sub">All LLM, OCR, translate</div>
      </div>
    </div>

    <h2 style="margin-top:18px;">Cost by component (annual)</h2>
    <div class="breakdown" id="componentBreakdown"></div>

    <h2 style="margin-top:18px;">Cost by stage (annual)</h2>
    <div class="breakdown" id="stageBreakdown"></div>

    <h2 style="margin-top:18px;">Volume scaffolding</h2>
    <div class="breakdown" id="volumeBreakdown"></div>

    <div class="note" id="narrativeNote"></div>
  </div>

</div>

<div class="footer">
  Math: annual_cost = LLM input cost + LLM output cost + Azure DI OCR cost + Translator cost. Per-email LLM token mix is the sum
  of classification, decision, reply-drafting, plus per-page extraction tokens applied to the percentage of pages flagged for LLM
  pass. OCR cost charges every attached page once. Unit prices default to Azure public list pricing and are editable.
  This calculator is the same model used in the Pricing schedule worked example; treat outputs as the proposal floor and adjust
  before final RFP submission.
</div>

</div>

<script>
const DEFAULTS = {
  emailsPerYear: 880000, attachPerEmail: 5, pagesPerAttachment: 10, bodyKb: 6,
  classifyIn: 1100, classifyOut: 180,
  extractPagePct: 35, extractInPerPage: 1500, extractOutPerPage: 600,
  decideIn: 800, decideOut: 200,
  replyIn: 1500, replyOut: 500,
  translatePct: 25, translateChars: 1800,
  llmFamily: "gpt54",
  llmInPrice: 2.50, llmCachedPrice: 0.25, cachedPct: 50, llmOutPrice: 15.00,
  ocrModel: "read", ocrPrice: 1.50, translatePrice: 10.00,
};

// Azure Document Intelligence price book (S0 pay-as-you-go, per 1k pages).
// Sourced from prices.azure.com retail API, productName == "Azure Document Intelligence".
const OCR_PRICES = {
  read:         1.50,
  layout:      10.00,
  prebuilt:    10.00,
  custom:      30.00,
  custom_gen:  30.00,
  classifier:   3.00,
};

// GPT-5.x price book (per 1M tokens). Values from OpenAI public pricing.
const LLM_PRICES = {
  gpt54:     { in: 2.50,  cached: 0.25,   out: 15.00 },
  gpt54mini: { in: 0.75,  cached: 0.075,  out: 4.50  },
  gpt54nano: { in: 0.20,  cached: 0.02,   out: 1.25  },
  gpt54pro:  { in: 30.00, cached: null,   out: 180.00 },
  gpt55:     { in: 5.00,  cached: 0.50,   out: 30.00 },
  gpt55pro:  { in: 30.00, cached: null,   out: 180.00 },
};

function $(id) { return document.getElementById(id); }
function num(id) { return Number($(id).value || 0); }
function fmtMoney(v, dp=0) {
  if (Math.abs(v) >= 1000000) return "$" + (v/1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1000)    return "$" + (v/1000).toFixed(dp===0?1:dp) + "k";
  return "$" + v.toFixed(dp);
}
function fmtMoneyExact(v, dp=2) {
  return "$" + v.toFixed(dp).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}
function fmtNum(v) {
  return Math.round(v).toLocaleString();
}
function fmtTokens(v) {
  if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + "M";
  if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(0) + "K";
  return v.toFixed(0);
}

function recompute() {
  // Inputs
  const emails = num("emailsPerYear");
  const attach = num("attachPerEmail");
  const ppa    = num("pagesPerAttachment");
  const totalPages = emails * attach * ppa;
  const llmPages   = totalPages * num("extractPagePct") / 100;

  // Per-email LLM tokens
  const tokens = {
    classifyIn:  num("classifyIn"),
    classifyOut: num("classifyOut"),
    extractIn:   llmPages * num("extractInPerPage") / emails,
    extractOut:  llmPages * num("extractOutPerPage") / emails,
    decideIn:    num("decideIn"),
    decideOut:   num("decideOut"),
    replyIn:     num("replyIn"),
    replyOut:    num("replyOut"),
  };
  const inPerEmail  = tokens.classifyIn + tokens.extractIn + tokens.decideIn + tokens.replyIn;
  const outPerEmail = tokens.classifyOut + tokens.extractOut + tokens.decideOut + tokens.replyOut;
  const totalIn  = inPerEmail  * emails;
  const totalOut = outPerEmail * emails;

  // Translation
  const tEmails = emails * num("translatePct") / 100;
  const tChars  = tEmails * num("translateChars");

  // Unit prices
  const llmInPx     = num("llmInPrice");
  const llmCachedPx = num("llmCachedPrice");
  const cachedPct   = num("cachedPct") / 100;
  const llmOutPx    = num("llmOutPrice");
  const ocrPx       = num("ocrPrice");
  const trPx        = num("translatePrice");

  // Effective LLM input price = mix of cached and uncached
  const effectiveInPx = llmInPx * (1 - cachedPct) + llmCachedPx * cachedPct;

  // Component costs (annual USD)
  const ocrCost     = totalPages / 1000 * ocrPx;
  const llmInCost   = totalIn  / 1e6 * effectiveInPx;
  const llmOutCost  = totalOut / 1e6 * llmOutPx;
  const trCost      = tChars   / 1e6 * trPx;
  const annual = ocrCost + llmInCost + llmOutCost + trCost;
  const perEmail = emails ? annual / emails : 0;

  // Stage breakdown (annual, derived from token mix)
  const intakeIn  = tokens.classifyIn  * emails;
  const intakeOut = tokens.classifyOut * emails;
  const extractIn = (tokens.extractIn  * emails);
  const extractOut= (tokens.extractOut * emails);
  const decideIn  = tokens.decideIn    * emails;
  const decideOut = tokens.decideOut   * emails;
  const replyIn   = tokens.replyIn     * emails;
  const replyOut  = tokens.replyOut    * emails;

  const stageCosts = {
    "Intake (classification)":    intakeIn  / 1e6 * effectiveInPx + intakeOut  / 1e6 * llmOutPx,
    "Extraction (OCR + LLM)":     ocrCost + extractIn / 1e6 * effectiveInPx + extractOut / 1e6 * llmOutPx,
    "Decision (four-gate)":       decideIn  / 1e6 * effectiveInPx + decideOut  / 1e6 * llmOutPx,
    "Communication (reply + translate)": replyIn  / 1e6 * effectiveInPx + replyOut  / 1e6 * llmOutPx + trCost,
  };

  // Render totals
  $("annualTotal").textContent = fmtMoneyExact(annual, 0);
  $("annualPerEmail").textContent = fmtMoneyExact(perEmail, 4) + " per email";
  $("monthlyTotal").textContent = fmtMoneyExact(annual / 12, 0);
  $("monthlyVol").textContent = fmtNum(emails / 12) + " emails / month";
  $("perCase").textContent = fmtMoneyExact(perEmail, 4);

  // Components
  const components = [
    ["LLM input tokens",           llmInCost,  totalIn, "tokens"],
    ["LLM output tokens",          llmOutCost, totalOut, "tokens"],
    ["Azure DI OCR pages",         ocrCost,    totalPages, "pages"],
    ["Translator (characters)",    trCost,     tChars, "chars"],
  ];
  const cbody = components.map(([lbl, cost, units, unitKind]) => {
    const pct = annual ? (cost / annual * 100) : 0;
    return `<div class="row">
      <div class="lbl">${lbl}<span class="h">${fmtTokens(units)} ${unitKind} / yr</span></div>
      <div class="v">${fmtMoneyExact(cost, 0)}</div>
      <div class="p">${pct.toFixed(1)}%</div>
    </div>`;
  }).join("");
  $("componentBreakdown").innerHTML = cbody;

  // Stages
  const stageMax = Math.max(1, ...Object.values(stageCosts));
  const sbody = Object.entries(stageCosts).map(([name, cost]) => {
    const pct = annual ? (cost / annual * 100) : 0;
    const w = cost / stageMax * 100;
    return `<div class="row stage-row">
      <div class="lbl">${name}<div class="bar"><i style="width:${w}%"></i></div></div>
      <div class="v">${fmtMoneyExact(cost, 0)}</div>
      <div class="p">${pct.toFixed(1)}%</div>
    </div>`;
  }).join("");
  $("stageBreakdown").innerHTML = sbody;

  // Volume scaffolding
  const vbody = `
    <div class="row"><div class="lbl">Total OCR pages</div><div class="v">${fmtNum(totalPages)}</div><div class="p">/ yr</div></div>
    <div class="row"><div class="lbl">LLM-processed pages</div><div class="v">${fmtNum(llmPages)}</div><div class="p">/ yr</div></div>
    <div class="row"><div class="lbl">Total LLM input tokens</div><div class="v">${fmtTokens(totalIn)}</div><div class="p">/ yr</div></div>
    <div class="row"><div class="lbl">Total LLM output tokens</div><div class="v">${fmtTokens(totalOut)}</div><div class="p">/ yr</div></div>
    <div class="row"><div class="lbl">Emails requiring translation</div><div class="v">${fmtNum(tEmails)}</div><div class="p">/ yr</div></div>
    <div class="row"><div class="lbl">Translation characters</div><div class="v">${fmtTokens(tChars)}</div><div class="p">/ yr</div></div>
  `;
  $("volumeBreakdown").innerHTML = vbody;

  // Narrative
  const topStage = Object.entries(stageCosts).sort((a,b) => b[1] - a[1])[0];
  const topPct = annual ? (topStage[1] / annual * 100) : 0;
  $("narrativeNote").innerHTML =
    `<b>Where the spend lives:</b> ${topStage[0]} is the dominant component at <b>${topPct.toFixed(0)}%</b> of annual spend (${fmtMoneyExact(topStage[1], 0)}). ` +
    `Per-case cost lands at <b>${fmtMoneyExact(perEmail, 4)}</b>, which is the dollar floor the proposal anchors on. ` +
    `Halving the per-page LLM extraction percentage (currently ${num("extractPagePct")}%) cuts annual spend by roughly ` +
    `<b>${fmtMoneyExact(extractIn / 1e6 * llmInPx / 2 + extractOut / 1e6 * llmOutPx / 2, 0)}</b>.`;

  // Persist to query string for shareable link
  updateUrl();
}

function updateUrl() {
  const params = new URLSearchParams();
  for (const k of Object.keys(DEFAULTS)) {
    const el = $(k);
    if (!el) continue;
    if (String(el.value) !== String(DEFAULTS[k])) {
      params.set(k, el.value);
    }
  }
  const q = params.toString();
  history.replaceState(null, "", q ? "?" + q : window.location.pathname);
}

function loadFromUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const [k, v] of params) {
    if ($(k)) $(k).value = v;
  }
}

function resetDefaults() {
  for (const [k, v] of Object.entries(DEFAULTS)) {
    if ($(k)) $(k).value = v;
  }
  recompute();
}

function copyShareLink() {
  navigator.clipboard.writeText(window.location.href);
  const btn = event.target;
  const original = btn.textContent;
  btn.textContent = "Copied ✓";
  setTimeout(() => { btn.textContent = original; }, 1500);
}

function onLlmFamilyChange() {
  const fam = $("llmFamily").value;
  if (fam in LLM_PRICES) {
    const p = LLM_PRICES[fam];
    $("llmInPrice").value  = p.in;
    $("llmOutPrice").value = p.out;
    if (p.cached != null) {
      $("llmCachedPrice").value = p.cached;
    } else {
      // Pro tiers have no cached price; set to the standard input price so
      // the cached blend reduces to the normal cost.
      $("llmCachedPrice").value = p.in;
    }
  }
  recompute();
}

function onOcrModelChange() {
  const m = $("ocrModel").value;
  if (m in OCR_PRICES) {
    $("ocrPrice").value = OCR_PRICES[m].toFixed(2);
  }
  recompute();
}

// Wire up
document.addEventListener("DOMContentLoaded", () => {
  loadFromUrl();
  for (const k of Object.keys(DEFAULTS)) {
    const el = $(k);
    if (!el) continue;
    if (el.tagName === "SELECT") {
      if (k === "ocrModel") el.addEventListener("change", onOcrModelChange);
      else                  el.addEventListener("change", onLlmFamilyChange);
    } else {
      el.addEventListener("input", recompute);
    }
  }
  recompute();
});
</script>
</body>
</html>
"""

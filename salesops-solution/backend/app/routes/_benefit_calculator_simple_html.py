"""Simplified, customer-facing benefit calculator served at
/api/docs/rfp-reply/benefit-case-simple.

Strips the full calculator down to the six inputs that actually move the
outcome (volume, team size, cost per FTE, efficiency target, platform cost,
implementation cost). Hides the token mix / OCR / translation / ramp curves
that confuse a non-technical buyer in a first conversation.

Headline order is deliberate:
  1. Payback months (the lead number the customer remembers)
  2. Annual recurring savings
  3. Three-year net benefit
  4. ROI

A side-by-side ZBrain vs competitor block makes the time-to-value advantage
visible at a glance. All math + branding match the full calculator so the
two views never disagree on the numbers."""

BENEFIT_CALCULATOR_SIMPLE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Keysight SalesOps · Benefit case · ZBrain</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    --ink: #131426; --muted: #6B7280; --rule: #E5E7EB; --surface: #F8FAFC;
    --accent: #1A55F9; --accent-soft: #1A55F910;
    --ok: #1F8A4C; --ok-soft: #E1F4E8;
    --warn: #C77700;
    --rose: #B91C1C; --rose-soft: #FEECEC;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, Inter, "Segoe UI", Roboto, sans-serif;
    background: var(--surface); color: var(--ink); line-height: 1.55;
  }
  .shell { max-width: 1240px; margin: 0 auto; padding: 28px 24px 64px; }

  /* ---------- Cover ---------- */
  .cover {
    background: linear-gradient(135deg, #0E1230 0%, #1E2A4D 100%);
    color: white; border-radius: 14px; padding: 28px 32px; margin-bottom: 22px;
    border-top: 4px solid #1A55F9;
    box-shadow: 0 8px 28px rgba(15,30,80,.18);
    position: relative; overflow: hidden;
  }
  .cover::after {
    content: ""; position: absolute; right: -80px; top: -80px;
    width: 280px; height: 280px; border-radius: 50%;
    background: radial-gradient(circle, rgba(26,85,249,.18) 0%, transparent 70%);
    pointer-events: none;
  }
  .cover .eyebrow { font-size: 11px; font-weight: 700; color: #6E8AE8;
                    letter-spacing: 0.16em; text-transform: uppercase; }
  .cover h1 { font-size: 28px; margin: 8px 0 8px; font-weight: 600;
              letter-spacing: -0.02em; color: #F5F7FB; }
  .cover p { font-size: 14.5px; max-width: 880px; color: #C7CEE2; margin: 0;
             line-height: 1.6; }
  .cover h1, .cover p, .cover .eyebrow { position: relative; z-index: 1; }

  /* ---------- Headline tiles ---------- */
  .headline {
    display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 14px;
    margin: 0 0 26px;
  }
  @media (max-width: 1000px) { .headline { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 560px)  { .headline { grid-template-columns: 1fr; } }
  .hl {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 18px 20px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
    position: relative;
  }
  .hl .lbl {
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.12em;
    color: var(--muted); font-weight: 700;
  }
  .hl .val {
    font-size: 32px; font-weight: 700; color: var(--ink);
    font-variant-numeric: tabular-nums; margin-top: 6px;
    letter-spacing: -0.02em;
  }
  .hl .sub { font-size: 11.5px; color: var(--muted); margin-top: 4px; line-height: 1.5; }

  .hl.hero {
    background: linear-gradient(180deg, #EAF1FF, white 70%);
    border-color: #C9D8FB;
  }
  .hl.hero .lbl { color: var(--accent); }
  .hl.hero .val {
    font-size: 44px; color: var(--accent);
  }
  .hl.ok    { background: linear-gradient(180deg,#E8F5EE,white 70%); border-color: #B9DEC8; }
  .hl.ok    .val { color: var(--ok); }
  .hl.accent{ background: linear-gradient(180deg,#F5F7FF,white 70%); border-color: #DCE2F2; }
  .hl.accent .val { color: var(--accent); }

  /* ---------- Inputs + summary panel ---------- */
  .panel {
    display: grid; grid-template-columns: 1fr 1fr; gap: 18px;
    margin-bottom: 26px;
  }
  @media (max-width: 1000px) { .panel { grid-template-columns: 1fr; } }
  .card {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 22px 24px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
  }
  .card h2 {
    font-size: 16px; margin: 0 0 4px;
    letter-spacing: -0.01em; color: var(--ink);
  }
  .card .h2sub { font-size: 12.5px; color: var(--muted); margin: 0 0 18px; }

  .input-row {
    display: grid; grid-template-columns: 1fr 160px; gap: 14px;
    align-items: center; margin: 0 0 14px;
  }
  .input-row label {
    display: flex; flex-direction: column; gap: 2px;
    font-size: 13.5px; color: var(--ink); font-weight: 500;
  }
  .input-row label .hint { font-size: 11.5px; color: var(--muted); font-weight: 400; }
  .input-row input, .input-row select {
    width: 100%; padding: 9px 11px;
    border: 1px solid var(--rule); border-radius: 8px;
    background: white; color: var(--ink); font-size: 14px;
    font-variant-numeric: tabular-nums; text-align: right;
  }
  .input-row input:focus, .input-row select:focus {
    outline: none; border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(26,85,249,0.12);
  }
  .input-row .with-prefix { position: relative; }
  .input-row .with-prefix::before {
    content: attr(data-prefix);
    position: absolute; left: 11px; top: 50%; transform: translateY(-50%);
    color: var(--muted); font-size: 13px;
    pointer-events: none;
  }
  .input-row .with-prefix input { padding-left: 22px; text-align: right; }
  .input-row .with-suffix { position: relative; }
  .input-row .with-suffix::after {
    content: attr(data-suffix);
    position: absolute; right: 11px; top: 50%; transform: translateY(-50%);
    color: var(--muted); font-size: 13px;
    pointer-events: none;
  }
  .input-row .with-suffix input { padding-right: 32px; }

  /* ---------- Summary numbers ---------- */
  .summary { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .summary .cell {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 10px; padding: 14px 16px;
  }
  .summary .cell .lbl {
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--muted); font-weight: 700;
  }
  .summary .cell .val {
    font-size: 21px; font-weight: 700; margin-top: 4px;
    font-variant-numeric: tabular-nums; letter-spacing: -0.015em;
  }
  .summary .cell .sub { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
  .summary .cell.ok .val { color: var(--ok); }
  .summary .cell.accent .val { color: var(--accent); }

  /* ---------- Competitor head-to-head ---------- */
  .compare {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 24px 28px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
    margin-bottom: 26px;
  }
  .compare h2 { font-size: 17px; margin: 0 0 4px; letter-spacing: -0.01em; }
  .compare .sub { font-size: 12.5px; color: var(--muted); margin: 0 0 18px; }
  .vs {
    display: grid;
    grid-template-columns: 1fr 60px 1fr;
    gap: 16px; align-items: stretch;
  }
  @media (max-width: 800px) { .vs { grid-template-columns: 1fr; } }
  .vs .col {
    background: var(--surface);
    border: 1px solid var(--rule); border-radius: 12px;
    padding: 18px 20px;
  }
  .vs .col.zbrain {
    background: linear-gradient(180deg, #EAF1FF, white 70%);
    border-color: #C9D8FB;
  }
  .vs .col.comp {
    background: linear-gradient(180deg, #F8FAFC, white 70%);
  }
  .vs .col .name {
    font-size: 13px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.12em;
    display: flex; align-items: center; gap: 8px;
  }
  .vs .col.zbrain .name { color: var(--accent); }
  .vs .col .name .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .vs .col.zbrain .name .dot { background: var(--accent); }
  .vs .col .row {
    display: grid; grid-template-columns: 1fr auto; gap: 8px;
    padding: 10px 0; border-top: 1px solid var(--rule);
  }
  .vs .col .row:nth-child(2) { border-top: none; margin-top: 8px; }
  .vs .col .row .k { font-size: 12.5px; color: var(--muted); }
  .vs .col .row .v {
    font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .vs .col.zbrain .row .v { color: var(--accent); }
  .vs .vs-mid {
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; color: var(--muted); font-weight: 700;
    letter-spacing: 0.12em;
  }
  .compare .takeaway {
    margin-top: 18px; padding: 14px 18px;
    background: #F5F7FF; border-left: 4px solid var(--accent);
    border-radius: 8px;
    font-size: 13.5px; line-height: 1.55; color: var(--ink);
  }
  .compare .takeaway b { color: var(--accent); }

  /* ---------- Footer ---------- */
  .footnote {
    font-size: 11.5px; color: var(--muted);
    margin-top: 26px; padding-top: 16px;
    border-top: 1px solid var(--rule); line-height: 1.6;
  }

  @media print {
    body { background: white; }
    .shell { padding: 0; max-width: 100%; }
    .cover, .compare, .card { box-shadow: none; }
  }
</style>
</head>
<body>
<div class="shell">

  <div class="cover">
    <div class="eyebrow">Keysight Project · SalesOps Automation</div>
    <h1>Benefit case</h1>
    <p>
      Adjust the six inputs that matter. Payback, annual savings, three-year net, and ROI
      recompute live, alongside a side-by-side view of ZBrain versus a typical systems
      integrator delivery.
    </p>
  </div>

  <!-- Headline tiles -->
  <div class="headline">
    <div class="hl hero">
      <div class="lbl">Payback period</div>
      <div class="val" id="hlPayback">--</div>
      <div class="sub" id="hlPaybackSub">months to break even on implementation</div>
    </div>
    <div class="hl ok">
      <div class="lbl">Annual recurring savings</div>
      <div class="val" id="hlAnnual">--</div>
      <div class="sub">cash savings, net of platform &amp; governance</div>
    </div>
    <div class="hl accent">
      <div class="lbl">Three-year net benefit</div>
      <div class="val" id="hlNet">--</div>
      <div class="sub">benefit minus total cost over 36 months</div>
    </div>
    <div class="hl">
      <div class="lbl">Three-year ROI</div>
      <div class="val" id="hlRoi">--</div>
      <div class="sub" id="hlNpv">NPV (10% discount): --</div>
    </div>
  </div>

  <!-- Inputs + summary -->
  <div class="panel">
    <div class="card">
      <h2>Inputs</h2>
      <p class="h2sub">Edit any field to see the headline numbers recompute instantly.</p>

      <div class="input-row">
        <label>
          Annual inbound emails
          <span class="hint">Customer requests handled by the workflow per year</span>
        </label>
        <input type="number" id="emails" value="880000" min="0" step="10000" />
      </div>

      <div class="input-row">
        <label>
          Team size in scope (FTE)
          <span class="hint">CSRs, order ops, and case handlers the workflow supports</span>
        </label>
        <input type="number" id="ftes" value="650" min="0" step="10" />
      </div>

      <div class="input-row">
        <label>
          Fully-loaded cost per FTE
          <span class="hint">Annual cost including benefits and overhead</span>
        </label>
        <div class="with-prefix" data-prefix="$">
          <input type="number" id="costPerFte" value="15000" min="0" step="500" />
        </div>
      </div>

      <div class="input-row">
        <label>
          Efficiency target
          <span class="hint">Share of the team's handle time removed by automation</span>
        </label>
        <div class="with-suffix" data-suffix="%">
          <input type="number" id="efficiency" value="65" min="0" max="90" step="1" />
        </div>
      </div>

      <div class="input-row">
        <label>
          Annual platform &amp; governance cost
          <span class="hint">ZBrain platform, model spend, and governance package</span>
        </label>
        <div class="with-prefix" data-prefix="$">
          <input type="number" id="annualCost" value="848000" min="0" step="10000" />
        </div>
      </div>

      <div class="input-row">
        <label>
          One-time implementation
          <span class="hint">Build, integrations, change management</span>
        </label>
        <div class="with-prefix" data-prefix="$">
          <input type="number" id="impl" value="1350000" min="0" step="50000" />
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Year-by-year</h2>
      <p class="h2sub">Cash benefit ramps over three years, net of the run cost each year.</p>

      <div class="summary">
        <div class="cell">
          <div class="lbl">Baseline annual cost</div>
          <div class="val" id="sumBaseline">--</div>
          <div class="sub" id="sumBaselineSub">team × cost per FTE</div>
        </div>
        <div class="cell ok">
          <div class="lbl">Annual cash savings</div>
          <div class="val" id="sumCash">--</div>
          <div class="sub" id="sumCashSub">at steady state</div>
        </div>
        <div class="cell">
          <div class="lbl">Year 1 net</div>
          <div class="val" id="sumY1">--</div>
          <div class="sub">includes one-time implementation</div>
        </div>
        <div class="cell">
          <div class="lbl">Year 2 net</div>
          <div class="val" id="sumY2">--</div>
          <div class="sub">recurring</div>
        </div>
        <div class="cell">
          <div class="lbl">Year 3 net</div>
          <div class="val" id="sumY3">--</div>
          <div class="sub">recurring</div>
        </div>
        <div class="cell accent">
          <div class="lbl">Three-year total cost</div>
          <div class="val" id="sumTotalCost">--</div>
          <div class="sub">platform + governance + impl</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Competitor head-to-head -->
  <div class="compare">
    <h2>ZBrain vs systems integrator alternative</h2>
    <p class="sub">Time-to-value and total cost over the same horizon. Edit the competitor side to match a vendor you are comparing against.</p>

    <div class="vs">
      <div class="col zbrain">
        <div class="name"><span class="dot"></span> ZBrain</div>
        <div class="row"><span class="k">Time to first production case</span><span class="v">8 weeks</span></div>
        <div class="row"><span class="k">Implementation</span><span class="v" id="zImpl">--</span></div>
        <div class="row"><span class="k">Annual run cost</span><span class="v" id="zAnnual">--</span></div>
        <div class="row"><span class="k">Three-year net benefit</span><span class="v" id="zNet">--</span></div>
      </div>
      <div class="vs-mid">VS</div>
      <div class="col comp">
        <div class="name"><span class="dot"></span> SI / competitor</div>
        <div class="row">
          <span class="k">Time to first production case</span>
          <span class="v">
            <input type="number" id="compStart" value="6" min="1" step="1"
              style="width:48px;padding:3px 6px;border:1px solid var(--rule);border-radius:6px;font-size:14px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;" />
            mo
          </span>
        </div>
        <div class="row">
          <span class="k">Implementation</span>
          <span class="v">
            $<input type="number" id="compImpl" value="1350000" min="0" step="50000"
              style="width:110px;padding:3px 6px;border:1px solid var(--rule);border-radius:6px;font-size:14px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;" />
          </span>
        </div>
        <div class="row">
          <span class="k">Annual run cost</span>
          <span class="v">
            $<input type="number" id="compAnnual" value="848000" min="0" step="10000"
              style="width:110px;padding:3px 6px;border:1px solid var(--rule);border-radius:6px;font-size:14px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;" />
          </span>
        </div>
        <div class="row"><span class="k">Three-year net benefit</span><span class="v" id="cNet">--</span></div>
      </div>
    </div>

    <div class="takeaway" id="takeaway">
      <!-- populated by JS -->
    </div>
  </div>

  <div class="footnote">
    Assumptions: ROI = (3-year net) / (3-year total cost). NPV uses a 10% discount rate over a 36-month horizon.
    Cash savings = (team × cost per FTE) × efficiency target × 70% cash redeployment, net of annual platform and governance cost.
    Three-year net benefit assumes 55% / 95% / 100% realisation across years 1, 2, and 3 to reflect onboarding ramp.
    The ZBrain side uses 8 weeks to first production case; the SI side uses your edit. All other inputs match the live page values.
  </div>

</div>

<script>
"use strict";
function $(id) { return document.getElementById(id); }
function num(id) { return Number($(id).value || 0); }
function fmt(v) {
  const neg = v < 0; v = Math.abs(v);
  let s;
  if (v >= 1e9) s = "$" + (v/1e9).toFixed(2) + "B";
  else if (v >= 1e6) s = "$" + (v/1e6).toFixed(2) + "M";
  else if (v >= 1e3) s = "$" + (v/1e3).toFixed(0) + "k";
  else s = "$" + v.toFixed(0);
  return neg ? "-" + s : s;
}
function fmtFull(v) {
  const neg = v < 0; v = Math.abs(v);
  return (neg ? "-" : "") + "$" + v.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// Realisation ramp + redeployment + discount are fixed in the simple view.
// (They are exposed in the full calculator if a buyer wants to interrogate.)
const Y1_REALISATION = 0.55;
const Y2_REALISATION = 0.95;
const Y3_REALISATION = 1.00;
const REDEPLOY = 0.70;
const DISCOUNT = 0.10;

function compute() {
  const emails = num("emails");
  const ftes = num("ftes");
  const cpf = num("costPerFte");
  const eff = num("efficiency") / 100;
  const annualCost = num("annualCost");
  const impl = num("impl");

  const baselineCost = ftes * cpf;
  const grossSavings = baselineCost * eff;
  const cashSavings = grossSavings * REDEPLOY;
  const steadyNet = cashSavings - annualCost;

  const y1Benefit = cashSavings * Y1_REALISATION;
  const y2Benefit = cashSavings * Y2_REALISATION;
  const y3Benefit = cashSavings * Y3_REALISATION;
  const y1Net = y1Benefit - annualCost - impl;
  const y2Net = y2Benefit - annualCost;
  const y3Net = y3Benefit - annualCost;
  const totalBenefit = y1Benefit + y2Benefit + y3Benefit;
  const totalCost = impl + 3 * annualCost;
  const totalNet = totalBenefit - totalCost;
  const roi = totalCost > 0 ? totalNet / totalCost : 0;

  const monthlySteady = steadyNet / 12;
  const paybackMonths = monthlySteady > 0 ? impl / monthlySteady : Infinity;

  const npv = y1Net/(1+DISCOUNT)
            + y2Net/Math.pow(1+DISCOUNT,2)
            + y3Net/Math.pow(1+DISCOUNT,3);

  // Competitor side
  const cImpl = num("compImpl");
  const cAnnual = num("compAnnual");
  const cStartMonths = num("compStart");
  const zStartMonths = 8 / 4.345; // 8 weeks
  const earlyMonths = Math.max(0, cStartMonths - zStartMonths);
  // 3-year benefit comparison: ZBrain has earlyMonths more months of savings at steady state.
  const zBenefit3y = totalBenefit;
  const zTotalCost3y = totalCost;
  const zNet3y = zBenefit3y - zTotalCost3y;
  // SI: assume same realisation curve but starts later. Total benefit reduced
  // by the share of the 36-month horizon lost to the slower start.
  const horizonMonths = 36;
  const cActiveMonths = Math.max(1, horizonMonths - cStartMonths);
  const cActiveFraction = cActiveMonths / horizonMonths;
  const cBenefit3y = (y1Benefit + y2Benefit + y3Benefit) * cActiveFraction;
  const cTotalCost3y = cImpl + 3 * cAnnual;
  const cNet3y = cBenefit3y - cTotalCost3y;

  return {
    baselineCost, cashSavings, steadyNet, paybackMonths,
    y1Net, y2Net, y3Net, totalBenefit, totalCost, totalNet, roi, npv,
    annualCost, impl, ftes, eff, emails,
    zBenefit3y, zTotalCost3y, zNet3y,
    cImpl, cAnnual, cStartMonths, cBenefit3y, cTotalCost3y, cNet3y,
    earlyMonths,
  };
}

function render() {
  const c = compute();
  $("hlPayback").textContent = isFinite(c.paybackMonths) ? c.paybackMonths.toFixed(1) + " mo" : "n/a";
  $("hlPaybackSub").textContent = isFinite(c.paybackMonths)
    ? "months to break even on implementation"
    : "annual savings do not cover platform cost at current inputs";
  $("hlAnnual").textContent = fmt(c.steadyNet);
  $("hlNet").textContent = fmt(c.totalNet);
  $("hlRoi").textContent = (c.roi * 100).toFixed(0) + "%";
  $("hlNpv").textContent = "NPV (10% discount): " + fmt(c.npv);

  $("sumBaseline").textContent = fmt(c.baselineCost);
  $("sumBaselineSub").textContent = c.ftes.toLocaleString() + " × " + fmtFull(c.baselineCost / Math.max(1, c.ftes));
  $("sumCash").textContent = fmt(c.cashSavings);
  $("sumCashSub").textContent = (c.eff * 100).toFixed(0) + "% efficiency · 70% redeployment";
  $("sumY1").textContent = fmt(c.y1Net);
  $("sumY2").textContent = fmt(c.y2Net);
  $("sumY3").textContent = fmt(c.y3Net);
  $("sumTotalCost").textContent = fmt(c.totalCost);

  $("zImpl").textContent    = fmt(c.impl);
  $("zAnnual").textContent  = fmt(c.annualCost);
  $("zNet").textContent     = fmt(c.zNet3y);
  $("cNet").textContent     = fmt(c.cNet3y);

  const advantage = c.zNet3y - c.cNet3y;
  const monthAdv = c.earlyMonths;
  const takeaway = $("takeaway");
  if (advantage > 0 && monthAdv > 0) {
    takeaway.innerHTML =
      "ZBrain delivers <b>" + fmt(advantage) + "</b> more three-year net benefit than the systems integrator path, " +
      "driven primarily by <b>" + monthAdv.toFixed(1) + " months</b> of earlier value capture. " +
      "The advantage compounds: every month of earlier go-live is roughly <b>" + fmt(c.steadyNet / 12) + "</b> in net savings.";
  } else if (advantage > 0) {
    takeaway.innerHTML =
      "ZBrain delivers <b>" + fmt(advantage) + "</b> more three-year net benefit than the systems integrator path. " +
      "The advantage comes from a lower run-rate cost at steady state.";
  } else {
    takeaway.innerHTML =
      "At the current inputs the two paths produce comparable three-year economics. " +
      "Adjust the competitor pricing or start time on the right to model a specific vendor.";
  }
}

document.addEventListener("input", function (ev) {
  if (ev.target && ev.target.tagName === "INPUT") render();
});
render();
</script>
</body>
</html>
"""

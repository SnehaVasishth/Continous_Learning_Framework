"""Interactive end-to-end calculator HTML served at
/api/docs/rfp-reply/benefit-case. Combines the cost calculator (volume, token
mix, OCR tier blend, translation, unit prices) with the benefit case (FTE
redeployment, efficiency target, ROI, payback, three-year NPV). Pure HTML +
vanilla JS so the page renders identically inside the in-app viewer and as a
self-contained file the client can run locally."""

BENEFIT_CALCULATOR_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Keysight SalesOps · End-to-end benefit case calculator · ZBrain</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    --ink: #131426; --muted: #6B7280; --rule: #E5E7EB; --surface: #F8FAFC;
    --accent: #1A55F9; --accent-soft: #1A55F910;
    --ok: #1F8A4C; --ok-soft: #E1F4E8; --warn: #C77700; --warn-soft: #FEF3C7;
    --danger: #B91C1C;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, Inter, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 0; background: var(--surface); color: var(--ink);
         line-height: 1.55; }
  .shell { max-width: 1400px; margin: 0 auto; padding: 28px 24px 64px; }

  .cover {
    background: linear-gradient(135deg, #0E1230 0%, #1E2A4D 100%);
    color: white; border-radius: 14px; padding: 30px 36px; margin-bottom: 22px;
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
  .cover h1 { font-size: 28px; margin: 8px 0 10px; font-weight: 600;
              letter-spacing: -0.02em; color: #F5F7FB; }
  .cover p { font-size: 14px; max-width: 920px; color: #C7CEE2; margin: 0;
             line-height: 1.6; }
  .cover .meta { font-size: 11px; margin-top: 14px; color: #8794B8;
                 letter-spacing: 0.06em; text-transform: uppercase; font-weight: 600; }
  .cover .facts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px;
                  position: relative; z-index: 1; }
  .cover .facts span { background: rgba(110,138,232,.14);
                       border: 1px solid rgba(110,138,232,.32);
                       color: #DCE2F2; padding: 5px 11px; border-radius: 999px;
                       font-size: 11.5px; font-weight: 500; }
  .cover .facts span b { color: #F5F7FB; font-weight: 700; margin-right: 4px; }
  .cover h1, .cover p, .cover .eyebrow { position: relative; z-index: 1; }

  .section { margin-top: 28px; }
  .section-head { display: flex; align-items: baseline; gap: 14px;
                  border-bottom: 2px solid var(--accent); padding-bottom: 8px;
                  margin-bottom: 16px; }
  .section-head .num { font-size: 13px; color: var(--accent); font-weight: 700;
                       letter-spacing: 0.14em; text-transform: uppercase; }
  .section-head h2 { font-size: 22px; margin: 0; letter-spacing: -0.01em; }
  .section-head .meta { margin-left: auto; font-size: 12px; color: var(--muted); }

  .headline { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
              margin: 0 0 22px; }
  @media (max-width: 1100px) { .headline { grid-template-columns: repeat(2, 1fr); } }
  .hl { background: white; border: 1px solid var(--rule); border-radius: 12px;
        padding: 16px 18px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }
  .hl .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em;
             color: var(--muted); font-weight: 700; }
  .hl .val { font-size: 28px; font-weight: 700; color: var(--ink);
             font-variant-numeric: tabular-nums; margin-top: 6px;
             letter-spacing: -0.02em; }
  .hl .sub { font-size: 11.5px; color: var(--muted); margin-top: 4px; }
  .hl.ok    { background: linear-gradient(180deg,#E8F5EE,white 70%); border-color: #B9DEC8; }
  .hl.ok    .val { color: var(--ok); }
  .hl.accent{ background: linear-gradient(180deg,#EAF1FF,white 70%); border-color: #C9D8FB; }
  .hl.accent .val { color: var(--accent); }
  .hl.warn  { background: linear-gradient(180deg,#FFF8E5,white 70%); border-color: #F0DCA0; }
  .hl.warn  .val { color: var(--warn); }

  .grid { display: grid; grid-template-columns: 1fr 1.5fr; gap: 22px; }
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
  .field select { width: 230px; padding: 6px 10px; border: 1px solid var(--rule);
                  border-radius: 6px; font-size: 13px; background: white;
                  font-family: inherit; color: var(--ink); }
  .field input.linked { background: #F0F6FF; border-color: #B8CFFA; }
  .linkbadge { font-size: 10px; color: var(--accent);
               margin-left: 6px; font-weight: 600; letter-spacing: 0.04em; }

  .section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em;
                   color: var(--muted); margin: 18px 0 6px; font-weight: 700;
                   display: flex; align-items: center; gap: 8px; }
  .section-title:first-child { margin-top: 0; }
  .section-title .badge { background: var(--accent-soft); color: var(--accent);
                          font-size: 10px; padding: 1px 7px; border-radius: 999px;
                          letter-spacing: 0.04em; font-weight: 700; }

  .btn-row { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .btn { font-size: 12px; padding: 7px 14px; border-radius: 6px;
         border: 1px solid var(--rule); background: white; color: var(--ink);
         cursor: pointer; font-family: inherit; font-weight: 500;
         text-decoration: none; display: inline-flex; align-items: center; gap: 5px; }
  .btn:hover { background: var(--surface); }
  .btn.primary { background: var(--accent); color: white; border-color: var(--accent); }
  .btn.primary:hover { opacity: 0.9; }

  .totals { display: grid; grid-template-columns: 1fr 1fr 1fr;
            gap: 12px; margin-bottom: 16px; }
  .total { background: var(--surface); border: 1px solid var(--rule);
           border-radius: 10px; padding: 12px 14px; }
  .total .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em;
                color: var(--muted); font-weight: 700; }
  .total .val { font-size: 22px; font-weight: 700; color: var(--ink);
                font-variant-numeric: tabular-nums; margin-top: 6px;
                letter-spacing: -0.02em; }
  .total .sub { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .total.big .val { color: var(--accent); font-size: 30px; }

  .breakdown { margin-top: 8px; }
  .row { display: grid; grid-template-columns: 1fr 110px 70px;
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

  .yeartable { width: 100%; border-collapse: collapse; margin-top: 8px;
               font-size: 13px; }
  .yeartable th, .yeartable td { padding: 9px 10px; text-align: right;
                                  font-variant-numeric: tabular-nums; }
  .yeartable th:first-child, .yeartable td:first-child {
    text-align: left; color: var(--ink); }
  .yeartable thead th { font-size: 10px; text-transform: uppercase;
                         letter-spacing: 0.1em; color: var(--muted);
                         border-bottom: 1px solid var(--rule); font-weight: 700; }
  .yeartable tbody tr { border-bottom: 1px solid var(--rule); }
  .yeartable tbody tr:last-child { border-bottom: none; }
  .yeartable tbody tr.total-row {
    background: var(--accent-soft); font-weight: 700;
    border-top: 2px solid var(--accent); border-bottom: none;
  }
  .yeartable tbody tr.total-row td { color: var(--ink); }
  .yeartable .pos { color: var(--ok); }
  .yeartable .neg { color: var(--danger); }

  .note { background: var(--accent-soft); border-left: 3px solid var(--accent);
          padding: 12px 14px; border-radius: 6px; font-size: 12.5px;
          color: #1F2937; margin-top: 14px; line-height: 1.6; }
  .note b { color: var(--ink); }
  .note.ok { background: var(--ok-soft); border-left-color: var(--ok); }
  .note.warn { background: var(--warn-soft); border-left-color: var(--warn); }

  .mix-chart { display: flex; height: 28px; border-radius: 6px; overflow: hidden;
               margin: 10px 0; border: 1px solid var(--rule); }
  .mix-chart > div { display: flex; align-items: center; justify-content: center;
                     font-size: 11px; color: white; font-weight: 600; }
  .mix-l4 { background: var(--ok); }
  .mix-l3 { background: var(--accent); }
  .mix-l2 { background: var(--warn); }

  .legend-row { display: flex; gap: 16px; font-size: 11.5px; color: var(--muted);
                margin-top: 4px; flex-wrap: wrap; }
  .legend-row span { display: inline-flex; align-items: center; gap: 5px; }
  .legend-row i { display: inline-block; width: 10px; height: 10px;
                  border-radius: 2px; }

  .footer { font-size: 11px; color: var(--muted); margin-top: 24px;
            line-height: 1.6; }
  .footer code { background: var(--surface); padding: 1px 5px; border-radius: 3px; }

  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--rule);
          margin-bottom: 16px; }
  .tab { padding: 8px 14px; font-size: 13px; cursor: pointer;
         border-bottom: 2px solid transparent; color: var(--muted);
         font-weight: 500; }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent);
                font-weight: 600; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  @media print {
    body { background: white; }
    .shell { max-width: 100%; padding: 16px; }
    .cover, .card { box-shadow: none; }
    .section { page-break-inside: avoid; }
  }
</style>
</head>
<body>
<div class="shell">

<div class="cover">
  <div class="eyebrow">Keysight SalesOps · End-to-end benefit case</div>
  <h1>SalesOps automation: cost &amp; benefit calculator</h1>
  <p>
    A live economic model for the SalesOps automation programme. The platform run cost
    is sized first from email volume, LLM token mix, OCR tier blend, and translation.
    That cost then converts directly into the three-year benefit case (FTE
    redeployment, annual net, ROI, payback, NPV) against the operational baseline
    below. Edit any input; every number recomputes instantly.
  </p>
  <div class="facts">
    <span><b>650</b> FTE in scope</span>
    <span><b>$15,000</b> fully-loaded cost / FTE</span>
    <span><b>65%</b> efficiency target</span>
    <span><b>880k</b> annual emails</span>
    <span><b>3-year</b> NPV horizon</span>
  </div>
</div>

<div id="sec-overview" class="section">
  <div class="section-head">
    <span class="num">0</span>
    <h2>Headline numbers</h2>
    <span class="meta">Live, recompute on every input change</span>
  </div>
  <div class="headline">
    <div class="hl ok">
      <div class="lbl">Annual net benefit</div>
      <div class="val" id="hlNet">$0</div>
      <div class="sub">Steady state, Year 2 onward</div>
    </div>
    <div class="hl accent">
      <div class="lbl">3-year NPV (10% discount)</div>
      <div class="val" id="hlNpv">$0</div>
      <div class="sub">Cumulative present value</div>
    </div>
    <div class="hl accent">
      <div class="lbl">ROI (3-year)</div>
      <div class="val" id="hlRoi">0%</div>
      <div class="sub">Return on total investment</div>
    </div>
    <div class="hl warn">
      <div class="lbl">Payback</div>
      <div class="val" id="hlPayback">0 mo</div>
      <div class="sub">Months to recoup implementation</div>
    </div>
  </div>
</div>

<div id="sec-cost" class="section">
  <div class="section-head">
    <span class="num">1</span>
    <h2>Cost calculator</h2>
    <span class="meta">Run cost &middot; flows into the benefit case below</span>
  </div>

  <div class="grid">

    <div class="card">
      <h2 class="l">Cost inputs &middot; editable</h2>

      <div class="section-title">Volume</div>
      <div class="field">
        <label>Annual inbound emails<span class="help">Per Keysight Q&amp;A baseline (~2k/day)</span></label>
        <input type="number" id="emailsPerYear" value="880000" min="0" step="10000" />
      </div>
      <div class="field">
        <label>Average attachments per email</label>
        <input type="number" id="attachPerEmail" value="5" min="0" step="0.1" />
      </div>
      <div class="field">
        <label>Average pages per attachment<span class="help">Mix of PO PDFs, scans, embedded items</span></label>
        <input type="number" id="pagesPerAttachment" value="10" min="0" step="0.5" />
      </div>

      <div class="section-title">LLM token mix (per email)</div>
      <div class="field">
        <label>Intake classification &middot; input tokens<span class="help">Email body + thread top, two-pass classifier</span></label>
        <input type="number" id="classifyIn" value="1100" min="0" step="50" />
      </div>
      <div class="field">
        <label>Intake classification &middot; output tokens</label>
        <input type="number" id="classifyOut" value="180" min="0" step="10" />
      </div>
      <div class="field">
        <label>% of pages that get LLM extraction<span class="help">PO-relevant pages only</span></label>
        <input type="number" id="extractPagePct" value="35" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>Per-page extraction &middot; input tokens<span class="help">OCR text + per-intent schema prompt</span></label>
        <input type="number" id="extractInPerPage" value="1500" min="0" step="50" />
      </div>
      <div class="field">
        <label>Per-page extraction &middot; output tokens</label>
        <input type="number" id="extractOutPerPage" value="600" min="0" step="50" />
      </div>
      <div class="field">
        <label>Decision call &middot; input tokens<span class="help">Context + four-gate scoring prompt</span></label>
        <input type="number" id="decideIn" value="800" min="0" step="50" />
      </div>
      <div class="field">
        <label>Decision call &middot; output tokens</label>
        <input type="number" id="decideOut" value="200" min="0" step="10" />
      </div>
      <div class="field">
        <label>Reply drafting &middot; input tokens<span class="help">Resolved entities + reply template + glossary</span></label>
        <input type="number" id="replyIn" value="1500" min="0" step="50" />
      </div>
      <div class="field">
        <label>Reply drafting &middot; output tokens</label>
        <input type="number" id="replyOut" value="500" min="0" step="10" />
      </div>

      <div class="section-title">Translation</div>
      <div class="field">
        <label>% of emails requiring translation</label>
        <input type="number" id="translatePct" value="25" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>Avg characters per translation pass<span class="help">Body + reply, both directions</span></label>
        <input type="number" id="translateChars" value="1800" min="0" step="100" />
      </div>

      <div class="section-title">Unit prices (USD)</div>
      <div class="field">
        <label>LLM family<span class="help">Switches input, cached, and output unit prices</span></label>
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
        <label>LLM input &middot; $ per 1M tokens</label>
        <input type="number" id="llmInPrice" value="2.50" min="0" step="0.05" />
      </div>
      <div class="field">
        <label>LLM cached input &middot; $ per 1M tokens<span class="help">Used when system + glossary prompts hit cache</span></label>
        <input type="number" id="llmCachedPrice" value="0.25" min="0" step="0.01" />
      </div>
      <div class="field">
        <label>% of input tokens hitting prompt cache</label>
        <input type="number" id="cachedPct" value="50" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>LLM output &middot; $ per 1M tokens</label>
        <input type="number" id="llmOutPrice" value="15.00" min="0" step="0.05" />
      </div>
      <div class="field">
        <label>OCR routing &middot; % Read tier<span class="help">$1.50/1k pages &middot; basic text on simple pages</span></label>
        <input type="number" id="ocrReadPct" value="80" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>OCR routing &middot; % Layout tier<span class="help">$10.00/1k pages &middot; PO line-item tables</span></label>
        <input type="number" id="ocrLayoutPct" value="18" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>OCR routing &middot; % Custom tier<span class="help">$30.00/1k pages &middot; trained templates</span></label>
        <input type="number" id="ocrCustomPct" value="2" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>Translation &middot; $ per 1M characters</label>
        <input type="number" id="translatePrice" value="10.00" min="0" step="0.5" />
      </div>

      <div class="btn-row">
        <button class="btn primary" onclick="resetCost()">Reset cost defaults</button>
      </div>
    </div>

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
          <div class="lbl">Per email</div>
          <div class="val" id="perCase">$0</div>
          <div class="sub">LLM + OCR + translate</div>
        </div>
      </div>

      <h2 style="margin-top:18px;">Cost by component (annual)</h2>
      <div class="breakdown" id="componentBreakdown"></div>

      <h2 style="margin-top:18px;">Cost by stage (annual)</h2>
      <div class="breakdown" id="stageBreakdown"></div>

      <div class="note" id="costNarrative"></div>
    </div>

  </div>
</div>

<div id="sec-benefit" class="section">
  <div class="section-head">
    <span class="num">2</span>
    <h2>Benefit case</h2>
    <span class="meta">FTE redeployment &middot; ROI &middot; payback &middot; 3-year NPV</span>
  </div>

  <div class="grid">

    <div class="card">
      <h2 class="l">Benefit inputs &middot; editable</h2>

      <div class="section-title">Operational baseline <span class="badge">CURRENT</span></div>
      <div class="field">
        <label>FTEs in scope<span class="help">SalesOps order-management team, range 600 to 700</span></label>
        <input type="number" id="ftes" value="650" min="0" step="10" />
      </div>
      <div class="field">
        <label>Fully-loaded annual cost per FTE (USD)<span class="help">Salary, benefits, overhead, tooling</span></label>
        <input type="number" id="costPerFte" value="15000" min="0" step="500" />
      </div>
      <div class="field">
        <label>Current avg handle time per email (min)<span class="help">Read, classify, look up, update, draft</span></label>
        <input type="number" id="baseHandleMin" value="12" min="0" step="0.5" />
      </div>
      <div class="field">
        <label>Productive hours per FTE per year<span class="help">2,080 raw minus PTO, training, meetings</span></label>
        <input type="number" id="fteHours" value="1700" min="0" step="50" />
      </div>

      <div class="section-title">Solution impact <span class="badge">TARGET</span></div>
      <div class="field">
        <label>Operational efficiency target (%)<span class="help">Share of current effort eliminated, range 60 to 70</span></label>
        <input type="number" id="efficiencyTarget" value="65" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>L4 auto-resolution rate (%)<span class="help">Confidence above 0.95, no human touch</span></label>
        <input type="number" id="l4Pct" value="35" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>L3 one-click review rate (%)<span class="help">Operator approves draft in one click</span></label>
        <input type="number" id="l3Pct" value="45" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>L2 full HITL rate (%)<span class="help">Operator handles edge case end-to-end</span></label>
        <input type="number" id="l2Pct" value="20" min="0" max="100" step="1" />
      </div>
      <div class="field">
        <label>L3 review time per email (min)</label>
        <input type="number" id="l3Min" value="1" min="0" step="0.5" />
      </div>
      <div class="field">
        <label>L2 HITL time per email (min)</label>
        <input type="number" id="l2Min" value="5" min="0" step="0.5" />
      </div>

      <div class="section-title">Investment</div>
      <div class="field">
        <label>Annual platform run cost (USD)<span class="help">Linked from cost calculator above; edit to override</span></label>
        <input type="number" id="platformCost" value="348000" min="0" step="1000" class="linked" />
      </div>
      <div class="field">
        <label>One-time implementation (USD)<span class="help">Build, integrate, train, UAT, hypercare</span></label>
        <input type="number" id="implCost" value="1350000" min="0" step="10000" />
      </div>
      <div class="field">
        <label>Annual support &amp; governance (USD)<span class="help">L1/L2 support, evals, drift monitoring, KB curation</span></label>
        <input type="number" id="govCost" value="500000" min="0" step="10000" />
      </div>

      <div class="section-title">Vs competitor <span class="badge">DELIVERY</span></div>
      <div class="field">
        <label>ZBrain time-to-first-value (weeks)<span class="help">V1 cuts go-live to ~8 weeks via accelerated build</span></label>
        <input type="number" id="zbrainStartWeeks" value="8" min="1" step="1" />
      </div>
      <div class="field">
        <label>Competitor time-to-first-value (months)<span class="help">Industry baseline for enterprise SalesOps automation</span></label>
        <input type="number" id="competitorStartMonths" value="6" min="1" step="1" />
      </div>
      <div class="field">
        <label>Ramp-up after first value (months)<span class="help">Linear ramp from 0 to 100% of steady-state benefit</span></label>
        <input type="number" id="rampMonths" value="6" min="1" step="1" />
      </div>
      <div class="field">
        <label>Comparison horizon (months)</label>
        <input type="number" id="horizonMonths" value="36" min="12" max="60" step="6" />
      </div>
      <div class="field">
        <label>Competitor one-time implementation (USD)<span class="help">Default matches ZBrain; edit if competitor pricing differs</span></label>
        <input type="number" id="competitorImpl" value="1350000" min="0" step="10000" />
      </div>
      <div class="field">
        <label>Competitor annual support &amp; governance (USD)<span class="help">Default matches ZBrain; edit if competitor pricing differs</span></label>
        <input type="number" id="competitorGov" value="500000" min="0" step="10000" />
      </div>
      <div class="field">
        <label>Competitor ramp duration (months)<span class="help">Linear 0 to cap; typical tier-1 SI runs 9 to 12 months to stabilize</span></label>
        <input type="number" id="competitorRampMonths" value="9" min="1" step="1" />
      </div>
      <div class="field">
        <label>Competitor steady-state cap (%)<span class="help">Realized benefit ceiling; default matches ZBrain. Drop below 100% to model a structural capability gap (less mature automation, slower iteration).</span></label>
        <input type="number" id="competitorRealizationCap" value="100" min="0" max="100" step="5" />
      </div>

      <div class="section-title">Financial assumptions</div>
      <div class="field">
        <label>Year-1 benefit ramp (%)<span class="help">Pilot months 1 to 3, scale-out months 4 to 12</span></label>
        <input type="number" id="y1Ramp" value="55" min="0" max="100" step="5" />
      </div>
      <div class="field">
        <label>Year-2 benefit realization (%)</label>
        <input type="number" id="y2Ramp" value="95" min="0" max="100" step="5" />
      </div>
      <div class="field">
        <label>Year-3 benefit realization (%)<span class="help">Continuous-learning compounding</span></label>
        <input type="number" id="y3Ramp" value="100" min="0" max="100" step="5" />
      </div>
      <div class="field">
        <label>Discount rate (%)<span class="help">Cost of capital for NPV</span></label>
        <input type="number" id="discount" value="10" min="0" max="30" step="0.5" />
      </div>
      <div class="field">
        <label>Redeployment factor (%)<span class="help">Share of freed FTE converting to cash</span></label>
        <input type="number" id="redeployFactor" value="70" min="0" max="100" step="5" />
      </div>

      <div class="btn-row">
        <button class="btn primary" onclick="resetBenefit()">Reset benefit defaults</button>
        <button class="btn" onclick="window.print()">Print / Save as PDF</button>
      </div>
    </div>

    <div class="card">
      <div class="tabs">
        <div class="tab active" data-tab="summary" onclick="selectTab('summary')">Summary</div>
        <div class="tab" data-tab="years" onclick="selectTab('years')">Year by year</div>
        <div class="tab" data-tab="ops" onclick="selectTab('ops')">Operational detail</div>
        <div class="tab" data-tab="sens" onclick="selectTab('sens')">Sensitivity</div>
      </div>

      <div class="tab-panel active" id="tab-summary">
        <div class="totals">
          <div class="total">
            <div class="lbl">Baseline cost (current)</div>
            <div class="val" id="baselineCost" style="color:var(--ok)">$0</div>
            <div class="sub" id="baselineCostSub">FTE x cost / FTE</div>
          </div>
          <div class="total">
            <div class="lbl">Target FTE (post-solution)</div>
            <div class="val" id="targetFte" style="color:var(--accent)">0</div>
            <div class="sub" id="targetFteSub">At efficiency target</div>
          </div>
          <div class="total">
            <div class="lbl">FTE freed</div>
            <div class="val" id="ftesFreed" style="color:var(--warn)">0</div>
            <div class="sub" id="ftesFreedSub">Cash + redeployment</div>
          </div>
        </div>

        <h2 style="margin-top:16px;">Annual run-rate (steady state)</h2>
        <div class="breakdown" id="annualBreakdown"></div>

        <h2 style="margin-top:16px;">Tiered autonomy mix</h2>
        <div class="mix-chart" id="mixChart"></div>
        <div class="legend-row">
          <span><i style="background:var(--ok)"></i> L4 auto-resolve</span>
          <span><i style="background:var(--accent)"></i> L3 one-click review</span>
          <span><i style="background:var(--warn)"></i> L2 full HITL</span>
        </div>

        <div class="note" id="summaryNarrative"></div>
      </div>

      <div class="tab-panel" id="tab-years">
        <h2 class="l" style="margin-bottom:6px;">Three-year financial case</h2>
        <p style="font-size:12.5px;color:var(--muted);margin:0 0 12px;">
          Year 1 includes the one-time implementation and a ramped benefit.
          Years 2 and 3 reach full realization with continuous-learning gains compounding.
        </p>
        <table class="yeartable">
          <thead>
            <tr><th>Line item</th><th>Year 1</th><th>Year 2</th><th>Year 3</th><th>Total</th></tr>
          </thead>
          <tbody id="yearTableBody"></tbody>
        </table>
        <div class="note ok" id="yearNarrative"></div>
      </div>

      <div class="tab-panel" id="tab-ops">
        <h2 class="l" style="margin-bottom:6px;">Operational metrics</h2>
        <p style="font-size:12.5px;color:var(--muted);margin:0 0 12px;">
          How the target state changes the day-to-day. These show up in the SLA schedule of the master agreement.
        </p>
        <div class="breakdown" id="opsBreakdown"></div>
        <h2 style="margin-top:18px;">Implied vs target efficiency</h2>
        <div class="breakdown" id="effCheck"></div>
        <div class="note" id="opsNarrative"></div>
      </div>

      <div class="tab-panel" id="tab-sens">
        <h2 class="l" style="margin-bottom:6px;">Sensitivity table</h2>
        <p style="font-size:12.5px;color:var(--muted);margin:0 0 12px;">
          Three-year NPV across efficiency target x per-FTE cost. Default cell highlighted.
        </p>
        <table class="yeartable" id="sensTable"></table>
        <h2 style="margin-top:18px;">Scenarios</h2>
        <div class="breakdown" id="scenarioBreakdown"></div>
      </div>

    </div>
  </div>
</div>

<div id="sec-vs" class="section">
  <div class="section-head">
    <span class="num">3</span>
    <h2>ZBrain vs competitor: time-to-value head start</h2>
    <span class="meta">Side-by-side cumulative cash position</span>
  </div>

  <div id="vsHeadline"></div>

  <div class="card" style="margin-bottom:18px;">
    <h2 class="l">Project timeline &middot; realized-benefit milestones</h2>
    <p style="font-size:13px;color:var(--muted);margin:6px 0 12px;">
      ZBrain's accelerated build puts V1 in production at week 8 and starts realizing
      benefit immediately. A tier-1 systems integrator follows a longer discovery / build / pilot
      cycle and does not begin realizing benefit until month 6, then runs a longer ramp.
    </p>
    <div id="vsTimeline"></div>
  </div>

  <div class="card" style="margin-bottom:18px;">
    <h2 class="l">Cumulative cash position over 36 months</h2>
    <p style="font-size:13px;color:var(--muted);margin:6px 0 12px;">
      Both projects pay the same implementation upfront. The shaded green area between
      the two lines is the cumulative head start ZBrain delivers month by month.
    </p>
    <div id="vsChart"></div>
  </div>

  <div class="grid">
    <div class="card">
      <h2 class="l">Assumptions used in this comparison</h2>
      <div id="vsAssumptions"></div>
    </div>
    <div class="card">
      <h2 class="l">Year-1 financial impact at 8-week start</h2>
      <p style="font-size:12.5px;color:var(--muted);margin:0 0 12px;">
        The numbers below use the time-to-value model directly. The conservative
        55% Year-1 realization shown in the main case (Section 2) is an additional
        risk haircut on top of these time-derived figures.
      </p>
      <div id="vsTable"></div>
      <div class="note ok" id="vsNarrative"></div>
    </div>
  </div>
</div>

<div class="footer">
  Math &middot; <b>Cost</b>: <code>annual = LLM input + LLM output + Azure DI OCR + Translation</code>; LLM input price is blended across cached and uncached at the cache-hit %.
  OCR is blended across Read / Layout / Custom by the routing percentages.
  <b>Benefit</b>: <code>gross = FTE x cost_per_FTE x efficiency</code>; <code>cash = gross x redeployment</code>;
  <code>net_year = cash x ramp - platform - support</code>; <code>NPV = sum(net_year / (1+r)^year)</code>;
  <code>payback = implementation / monthly_steady_net</code>.
</div>

</div>

<script>
/* ================ SECTION 1 - COST CALCULATOR ================ */
(function() {
  const DEFAULTS = {
    emailsPerYear: 880000, attachPerEmail: 5, pagesPerAttachment: 10,
    classifyIn: 1100, classifyOut: 180,
    extractPagePct: 35, extractInPerPage: 1500, extractOutPerPage: 600,
    decideIn: 800, decideOut: 200,
    replyIn: 1500, replyOut: 500,
    translatePct: 25, translateChars: 1800,
    llmFamily: "gpt54",
    llmInPrice: 2.50, llmCachedPrice: 0.25, cachedPct: 50, llmOutPrice: 15.00,
    ocrReadPct: 80, ocrLayoutPct: 18, ocrCustomPct: 2,
    translatePrice: 10.00,
  };

  const LLM_PRICES = {
    gpt54:     { in: 2.50,  cached: 0.25,   out: 15.00 },
    gpt54mini: { in: 0.75,  cached: 0.075,  out: 4.50  },
    gpt54nano: { in: 0.20,  cached: 0.02,   out: 1.25  },
    gpt54pro:  { in: 30.00, cached: null,   out: 180.00 },
    gpt55:     { in: 5.00,  cached: 0.50,   out: 30.00 },
    gpt55pro:  { in: 30.00, cached: null,   out: 180.00 },
  };
  const OCR_READ = 1.50, OCR_LAYOUT = 10.00, OCR_CUSTOM = 30.00;

  function $(id) { return document.getElementById(id); }
  function n(id) { return Number($(id).value || 0); }
  function fm(v, dp) {
    dp = dp || 0;
    const neg = v < 0; v = Math.abs(v);
    return (neg ? "-" : "") + "$" + v.toFixed(dp).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  function fn(v) { return Math.round(v).toLocaleString(); }
  function ft(v) {
    if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(2) + "B";
    if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + "M";
    if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(0) + "K";
    return v.toFixed(0);
  }

  function recompute() {
    const emails = n("emailsPerYear");
    const attach = n("attachPerEmail");
    const ppa = n("pagesPerAttachment");
    const totalPages = emails * attach * ppa;
    const llmPages = totalPages * n("extractPagePct") / 100;

    const tokens = {
      classifyIn:  n("classifyIn"),
      classifyOut: n("classifyOut"),
      extractIn:   llmPages * n("extractInPerPage") / Math.max(1, emails),
      extractOut:  llmPages * n("extractOutPerPage") / Math.max(1, emails),
      decideIn:    n("decideIn"),
      decideOut:   n("decideOut"),
      replyIn:     n("replyIn"),
      replyOut:    n("replyOut"),
    };
    const inPerEmail = tokens.classifyIn + tokens.extractIn + tokens.decideIn + tokens.replyIn;
    const outPerEmail = tokens.classifyOut + tokens.extractOut + tokens.decideOut + tokens.replyOut;
    const totalIn = inPerEmail * emails;
    const totalOut = outPerEmail * emails;

    const tEmails = emails * n("translatePct") / 100;
    const tChars = tEmails * n("translateChars");

    const llmIn = n("llmInPrice");
    const llmCached = n("llmCachedPrice");
    const cachedPct = n("cachedPct") / 100;
    const llmOut = n("llmOutPrice");
    const trPx = n("translatePrice");

    let readPct = n("ocrReadPct"), layPct = n("ocrLayoutPct"), cusPct = n("ocrCustomPct");
    const sum = readPct + layPct + cusPct;
    const ocrBlend = sum > 0
      ? (readPct * OCR_READ + layPct * OCR_LAYOUT + cusPct * OCR_CUSTOM) / sum
      : OCR_READ;

    const effIn = llmIn * (1 - cachedPct) + llmCached * cachedPct;

    const ocrCost = totalPages / 1000 * ocrBlend;
    const llmInCost = totalIn / 1e6 * effIn;
    const llmOutCost = totalOut / 1e6 * llmOut;
    const trCost = tChars / 1e6 * trPx;
    const annual = ocrCost + llmInCost + llmOutCost + trCost;
    const perEmail = emails ? annual / emails : 0;

    const intakeIn = tokens.classifyIn * emails;
    const intakeOut = tokens.classifyOut * emails;
    const extractIn = tokens.extractIn * emails;
    const extractOut = tokens.extractOut * emails;
    const decideIn = tokens.decideIn * emails;
    const decideOut = tokens.decideOut * emails;
    const replyIn = tokens.replyIn * emails;
    const replyOut = tokens.replyOut * emails;

    const stageCosts = {
      "Intake (classification)": intakeIn/1e6*effIn + intakeOut/1e6*llmOut,
      "Extraction (OCR + LLM)":  ocrCost + extractIn/1e6*effIn + extractOut/1e6*llmOut,
      "Decision (four-gate)":    decideIn/1e6*effIn + decideOut/1e6*llmOut,
      "Communication (reply + translate)": replyIn/1e6*effIn + replyOut/1e6*llmOut + trCost,
    };

    $("annualTotal").textContent = fm(annual);
    $("annualPerEmail").textContent = "$" + perEmail.toFixed(4) + " per email";
    $("monthlyTotal").textContent = fm(annual / 12);
    $("monthlyVol").textContent = fn(emails / 12) + " emails / month";
    $("perCase").textContent = "$" + perEmail.toFixed(4);

    const components = [
      ["LLM input tokens",  llmInCost,  totalIn,    "tokens"],
      ["LLM output tokens", llmOutCost, totalOut,   "tokens"],
      ["Azure DI OCR pages (blended)", ocrCost, totalPages, "pages"],
      ["Translator (characters)", trCost, tChars, "chars"],
    ];
    $("componentBreakdown").innerHTML = components.map(function(arr) {
      const lbl=arr[0], c=arr[1], u=arr[2], k=arr[3];
      const pct = annual ? (c / annual * 100) : 0;
      return '<div class="row"><div class="lbl">' + lbl
           + '<span class="h">' + ft(u) + ' ' + k + ' / yr</span></div>'
           + '<div class="v">' + fm(c) + '</div>'
           + '<div class="p">' + pct.toFixed(1) + '%</div></div>';
    }).join("");

    const stageMax = Math.max(1, ...Object.values(stageCosts));
    $("stageBreakdown").innerHTML = Object.entries(stageCosts).map(function(e) {
      const name=e[0], c=e[1];
      const pct = annual ? (c / annual * 100) : 0;
      const w = c / stageMax * 100;
      return '<div class="row stage-row"><div class="lbl">' + name
           + '<div class="bar"><i style="width:' + w + '%"></i></div></div>'
           + '<div class="v">' + fm(c) + '</div>'
           + '<div class="p">' + pct.toFixed(1) + '%</div></div>';
    }).join("");

    const topStage = Object.entries(stageCosts).sort(function(a,b){return b[1]-a[1];})[0];
    const topPct = annual ? (topStage[1] / annual * 100) : 0;
    $("costNarrative").innerHTML =
      '<b>Where the spend lives:</b> ' + topStage[0] + ' is the dominant component at <b>'
      + topPct.toFixed(0) + '%</b> of annual spend (' + fm(topStage[1]) + '). '
      + 'Per-email cost lands at <b>$' + perEmail.toFixed(4) + '</b>. '
      + 'OCR routing is blended at <b>$' + ocrBlend.toFixed(2) + ' / 1k pages</b> ('
      + readPct + '% Read, ' + layPct + '% Layout, ' + cusPct + '% Custom).';

    window.__costAnnual = annual;
    window.__costPerEmail = perEmail;
    if (window.__syncBenefit) window.__syncBenefit();
  }

  function onFamily() {
    const f = $("llmFamily").value;
    if (f in LLM_PRICES) {
      const p = LLM_PRICES[f];
      $("llmInPrice").value = p.in;
      $("llmOutPrice").value = p.out;
      $("llmCachedPrice").value = p.cached != null ? p.cached : p.in;
    }
    recompute();
  }

  window.resetCost = function() {
    for (const k in DEFAULTS) {
      const el = document.getElementById(k);
      if (el) el.value = DEFAULTS[k];
    }
    recompute();
  };

  document.addEventListener("DOMContentLoaded", function() {
    for (const k in DEFAULTS) {
      const el = document.getElementById(k);
      if (!el) continue;
      if (k === "llmFamily") el.addEventListener("change", onFamily);
      else el.addEventListener("input", recompute);
    }
    recompute();
  });
})();

/* ================ SECTION 2 - BENEFIT CASE ================ */
(function() {
  const DEFAULTS = {
    ftes: 650, costPerFte: 15000,
    baseHandleMin: 12, fteHours: 1700,
    efficiencyTarget: 65,
    l4Pct: 35, l3Pct: 45, l2Pct: 20,
    l3Min: 1, l2Min: 5,
    platformCost: 348000,
    implCost: 1350000, govCost: 500000,
    y1Ramp: 55, y2Ramp: 95, y3Ramp: 100,
    discount: 10, redeployFactor: 70,
    zbrainStartWeeks: 8, competitorStartMonths: 6, rampMonths: 6, horizonMonths: 36,
    competitorImpl: 1350000, competitorGov: 500000,
    competitorRampMonths: 9, competitorRealizationCap: 100,
  };

  function $(id) { return document.getElementById(id); }
  function n(id) { return Number($(id).value || 0); }
  function fm(v) {
    const neg = v < 0; v = Math.abs(v);
    return (neg ? "-" : "") + "$" + v.toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  function fmShort(v) {
    const neg = v < 0; v = Math.abs(v);
    let s;
    if (v >= 1e9) s = "$" + (v/1e9).toFixed(2) + "B";
    else if (v >= 1e6) s = "$" + (v/1e6).toFixed(2) + "M";
    else if (v >= 1e3) s = "$" + (v/1e3).toFixed(1) + "k";
    else s = "$" + v.toFixed(0);
    return neg ? "-" + s : s;
  }
  function fnum(v, dp) { dp = dp || 0; return (Math.round(v * Math.pow(10,dp))/Math.pow(10,dp)).toLocaleString(); }

  let userOverrode = false;
  window.__syncBenefit = function() {
    if (userOverrode) return;
    if (typeof window.__costAnnual !== "number") return;
    const el = $("platformCost");
    el.value = Math.round(window.__costAnnual);
    compute_and_render();
  };

  function compute() {
    const ftes = n("ftes");
    const costPerFte = n("costPerFte");
    const baselineCost = ftes * costPerFte;
    const baseHandle = n("baseHandleMin");
    const fteHours = n("fteHours");

    const eff = n("efficiencyTarget") / 100;
    const redeploy = n("redeployFactor") / 100;

    const l4 = n("l4Pct") / 100;
    const l3 = n("l3Pct") / 100;
    const l2 = n("l2Pct") / 100;
    const l3Min = n("l3Min");
    const l2Min = n("l2Min");

    const platform = n("platformCost");
    const impl = n("implCost");
    const gov = n("govCost");

    const y1R = n("y1Ramp") / 100;
    const y2R = n("y2Ramp") / 100;
    const y3R = n("y3Ramp") / 100;
    const disc = n("discount") / 100;

    const newHandle = l4*0 + l3*l3Min + l2*l2Min;
    const impliedEff = baseHandle > 0 ? (1 - newHandle / baseHandle) : 0;

    const emails = Number(($("emailsPerYear") || {}).value) || 880000;
    const baseEmailsPerFte = (fteHours * 60) / Math.max(0.01, baseHandle);
    const baseFteNeeded = emails / Math.max(1, baseEmailsPerFte);
    const targetFteFromEff = ftes * (1 - eff);
    const ftesFreed = ftes - targetFteFromEff;

    const grossSavings = ftesFreed * costPerFte;
    const cashSavings = grossSavings * redeploy;
    const valueSavings = grossSavings * (1 - redeploy);

    const annualSolutionCost = platform + gov;
    const steadyNet = cashSavings - annualSolutionCost;
    const y1Benefit = cashSavings * y1R;
    const y1Cost = annualSolutionCost + impl;
    const y1Net = y1Benefit - y1Cost;
    const y2Benefit = cashSavings * y2R;
    const y2Net = y2Benefit - annualSolutionCost;
    const y3Benefit = cashSavings * y3R;
    const y3Net = y3Benefit - annualSolutionCost;

    const totalBenefit = y1Benefit + y2Benefit + y3Benefit;
    const totalCost = y1Cost + annualSolutionCost + annualSolutionCost;
    const totalNet = totalBenefit - totalCost;
    const roi = totalCost > 0 ? totalNet / totalCost : 0;

    const npv = y1Net/(1+disc) + y2Net/Math.pow(1+disc,2) + y3Net/Math.pow(1+disc,3);
    const monthlySteady = (cashSavings - annualSolutionCost) / 12;
    const paybackMonths = monthlySteady > 0 ? impl / monthlySteady : Infinity;

    const zbrainStartMonth = n("zbrainStartWeeks") / 4.345;
    const competitorStartMonth = n("competitorStartMonths");
    const rampMonths = Math.max(1, n("rampMonths"));
    const horizonMonths = Math.max(12, n("horizonMonths"));
    const competitorImpl = n("competitorImpl");
    const competitorGov = n("competitorGov");
    const competitorRampMonths = Math.max(1, n("competitorRampMonths"));
    const competitorRealizationCap = Math.max(0, Math.min(100, n("competitorRealizationCap")));

    return { ftes: ftes, costPerFte: costPerFte, baselineCost: baselineCost, emails: emails,
      baseHandle: baseHandle, fteHours: fteHours,
      eff: eff, redeploy: redeploy, l4: l4, l3: l3, l2: l2, l3Min: l3Min, l2Min: l2Min,
      newHandle: newHandle, impliedEff: impliedEff,
      baseEmailsPerFte: baseEmailsPerFte, baseFteNeeded: baseFteNeeded,
      targetFteFromEff: targetFteFromEff, ftesFreed: ftesFreed,
      grossSavings: grossSavings, cashSavings: cashSavings, valueSavings: valueSavings,
      platform: platform, impl: impl, gov: gov, annualSolutionCost: annualSolutionCost,
      steadyNet: steadyNet,
      y1Benefit: y1Benefit, y1Cost: y1Cost, y1Net: y1Net,
      y2Benefit: y2Benefit, y2Net: y2Net, y3Benefit: y3Benefit, y3Net: y3Net,
      totalBenefit: totalBenefit, totalCost: totalCost, totalNet: totalNet,
      roi: roi, npv: npv,
      monthlySteady: monthlySteady, paybackMonths: paybackMonths,
      y1R: y1R, y2R: y2R, y3R: y3R, disc: disc,
      zbrainStartMonth: zbrainStartMonth, competitorStartMonth: competitorStartMonth,
      rampMonths: rampMonths, horizonMonths: horizonMonths,
      competitorImpl: competitorImpl, competitorGov: competitorGov,
      competitorRampMonths: competitorRampMonths, competitorRealizationCap: competitorRealizationCap };
  }

  function simulateCum(startMonth, rampMonths, monthlyBenefit, monthlyRunCost, impl, horizon) {
    const points = [{ month: 0, cum: -impl, monthly: -impl }];
    let cum = -impl;
    for (let m = 1; m <= horizon; m++) {
      let inflow = 0, outflow = 0;
      if (m >= startMonth) {
        const elapsed = m - startMonth + 1;
        const pct = Math.min(1, elapsed / rampMonths);
        inflow = monthlyBenefit * pct;
        outflow = monthlyRunCost;
      }
      const monthlyNet = inflow - outflow;
      cum += monthlyNet;
      points.push({ month: m, cum: cum, monthly: monthlyNet });
    }
    return points;
  }

  function findPayback(points) {
    for (let i = 1; i < points.length; i++) {
      if (points[i].cum >= 0) {
        const prev = points[i-1];
        if (prev.cum < 0 && points[i].cum > prev.cum) {
          return prev.month + (-prev.cum) / (points[i].cum - prev.cum);
        }
        return points[i].month;
      }
    }
    return null;
  }

  function render(c) {
    $("hlNet").textContent = fm(c.steadyNet);
    $("hlNpv").textContent = fm(c.npv);
    $("hlRoi").textContent = (c.roi*100).toFixed(0) + "%";
    $("hlPayback").textContent = isFinite(c.paybackMonths) ? c.paybackMonths.toFixed(1) + " mo" : "n/a";

    $("baselineCost").textContent = fm(c.baselineCost);
    $("baselineCostSub").textContent = c.ftes + " FTE x " + fm(c.costPerFte);
    $("targetFte").textContent = fnum(c.targetFteFromEff);
    $("targetFteSub").textContent = "At " + (c.eff*100).toFixed(0) + "% efficiency";
    $("ftesFreed").textContent = fnum(c.ftesFreed);
    $("ftesFreedSub").textContent = (c.redeploy*100).toFixed(0) + "% cash, " + ((1-c.redeploy)*100).toFixed(0) + "% redeployed";

    const annual = [
      ["Gross FTE-equivalent value", c.grossSavings, "value"],
      ["&nbsp;&nbsp;Redeployed (non-cash)", -c.valueSavings, "non-cash"],
      ["&nbsp;&nbsp;Cash savings", c.cashSavings, "cash"],
      ["Platform run cost", -c.platform, "cost"],
      ["Support &amp; governance", -c.gov, "cost"],
      ["Annual net (steady state)", c.steadyNet, "net"],
    ];
    $("annualBreakdown").innerHTML = annual.map(function(arr){
      const lbl=arr[0], v=arr[1], tag=arr[2];
      const color = v >= 0 ? "var(--ok)" : "var(--danger)";
      const tagHtml = tag === "net" ? '<span style="color:var(--accent);font-weight:700;">NET</span>'
                    : tag === "cash" ? 'cash'
                    : tag === "non-cash" ? '<span style="color:var(--muted);">value</span>'
                    : tag === "cost" ? 'expense' : 'value';
      return '<div class="row"><div class="lbl">' + lbl + '</div>'
           + '<div class="v" style="color:' + color + '">' + fm(v) + '</div>'
           + '<div class="p">' + tagHtml + '</div></div>';
    }).join("");

    const tot = (c.l4 + c.l3 + c.l2) || 1;
    $("mixChart").innerHTML =
      '<div class="mix-l4" style="width:' + (c.l4/tot*100) + '%">L4 ' + (c.l4*100).toFixed(0) + '%</div>'
      + '<div class="mix-l3" style="width:' + (c.l3/tot*100) + '%">L3 ' + (c.l3*100).toFixed(0) + '%</div>'
      + '<div class="mix-l2" style="width:' + (c.l2/tot*100) + '%">L2 ' + (c.l2*100).toFixed(0) + '%</div>';

    $("summaryNarrative").innerHTML =
      '<b>Headline:</b> The solution converts <b>' + fnum(c.ftesFreed) + ' FTE</b> of operational effort ('
      + (c.eff*100).toFixed(0) + '% of the in-scope team) into <b>' + fm(c.cashSavings)
      + '</b> of annual cash savings after applying the ' + (c.redeploy*100).toFixed(0) + '% redeployment factor. '
      + 'Net of the ' + fm(c.platform) + ' platform run cost and ' + fm(c.gov) + ' annual support, that is '
      + '<b>' + fm(c.steadyNet) + ' net per year</b> at steady state. Three-year NPV at '
      + (c.disc*100).toFixed(1) + '% discount is <b>' + fm(c.npv) + '</b>; implementation is recouped in '
      + (isFinite(c.paybackMonths) ? '<b>' + c.paybackMonths.toFixed(1) + ' months</b>.' : '<i>n/a at current inputs.</i>');

    const rows = [
      ["Cash benefit (FTE released)", c.y1Benefit, c.y2Benefit, c.y3Benefit, c.y1Benefit + c.y2Benefit + c.y3Benefit, "pos"],
      ["Platform run cost", -c.platform, -c.platform, -c.platform, -(c.platform*3), "neg"],
      ["Support &amp; governance", -c.gov, -c.gov, -c.gov, -(c.gov*3), "neg"],
      ["Implementation (one-time)", -c.impl, 0, 0, -c.impl, "neg"],
      ["Net cash flow", c.y1Net, c.y2Net, c.y3Net, c.y1Net + c.y2Net + c.y3Net, "net"],
    ];
    $("yearTableBody").innerHTML = rows.map(function(arr){
      const lbl=arr[0], y1=arr[1], y2=arr[2], y3=arr[3], t=arr[4], tag=arr[5];
      const cls = tag === "net" ? "total-row" : "";
      function cc(v){return v >= 0 ? "pos" : "neg";}
      return '<tr class="' + cls + '"><td>' + lbl + '</td>'
           + '<td class="' + cc(y1) + '">' + fm(y1) + '</td>'
           + '<td class="' + cc(y2) + '">' + fm(y2) + '</td>'
           + '<td class="' + cc(y3) + '">' + fm(y3) + '</td>'
           + '<td class="' + cc(t) + '">' + fm(t) + '</td></tr>';
    }).join("");

    $("yearNarrative").innerHTML =
      '<b>Three-year case:</b> Cumulative net of <b>' + fm(c.totalNet) + '</b> against total investment of <b>'
      + fm(c.totalCost) + '</b>. Year 1 is intentionally conservative at ' + (c.y1R*100).toFixed(0)
      + '% benefit realization to cover the 3-month pilot, integration, and operator-training phase. '
      + 'Year 2 reaches ' + (c.y2R*100).toFixed(0) + '% as the L4 share grows under continuous learning. '
      + 'Year 3 holds at ' + (c.y3R*100).toFixed(0) + '%.';

    const perEmailDisplay = (window.__costPerEmail || 0).toFixed(4);
    const ops = [
      ["Current effort", "", ""],
      ["&nbsp;&nbsp;Baseline emails per FTE per year", fnum(c.baseEmailsPerFte), ""],
      ["&nbsp;&nbsp;FTE needed at baseline handle time", fnum(c.baseFteNeeded), ""],
      ["&nbsp;&nbsp;Annual FTE-minutes consumed", fnum(c.emails * c.baseHandle) + " min", ""],
      ["Target effort", "", ""],
      ["&nbsp;&nbsp;Weighted handle time per email", c.newHandle.toFixed(2) + " min", ""],
      ["&nbsp;&nbsp;Target FTE at " + (c.eff*100).toFixed(0) + "% efficiency", fnum(c.targetFteFromEff), ""],
      ["&nbsp;&nbsp;Annual FTE-minutes consumed", fnum(c.emails * c.newHandle) + " min", ""],
      ["Throughput &amp; quality (commitments)", "", ""],
      ["&nbsp;&nbsp;Avg cycle time", "P50 under 30 min, P95 under 4 hr", ""],
      ["&nbsp;&nbsp;SLA hit rate", "+12 to 18 pp on current", ""],
      ["&nbsp;&nbsp;Operator override rate", "Below 5% by month 12", ""],
      ["&nbsp;&nbsp;Cost per email (solution)", "$" + perEmailDisplay, ""],
    ];
    $("opsBreakdown").innerHTML = ops.map(function(arr){
      const lbl=arr[0], v=arr[1], tag=arr[2];
      const isHeader = !v;
      if (isHeader) {
        return '<div class="row" style="background:var(--surface);font-weight:700;border-radius:6px;padding:8px 10px;border-bottom:none;"><div class="lbl">' + lbl + '</div><div></div><div></div></div>';
      }
      return '<div class="row"><div class="lbl">' + lbl + '</div><div class="v">' + v + '</div><div class="p">' + tag + '</div></div>';
    }).join("");

    $("effCheck").innerHTML =
      '<div class="row"><div class="lbl">Operational efficiency target<span class="h">Manually set</span></div>'
      + '<div class="v">' + (c.eff*100).toFixed(0) + '%</div><div class="p">target</div></div>'
      + '<div class="row"><div class="lbl">Implied efficiency from L4/L3/L2 mix<span class="h">1 - (weighted handle time / baseline)</span></div>'
      + '<div class="v">' + (c.impliedEff*100).toFixed(1) + '%</div><div class="p">implied</div></div>'
      + '<div class="row"><div class="lbl">Delta (implied vs target)<span class="h">Should sit within 2 to 3 pp</span></div>'
      + '<div class="v" style="color:' + (Math.abs(c.impliedEff - c.eff) < 0.05 ? 'var(--ok)' : 'var(--warn)') + '">'
      + ((c.impliedEff - c.eff)*100).toFixed(1) + ' pp</div><div class="p">check</div></div>';

    $("opsNarrative").innerHTML =
      '<b>Reading the table:</b> the target handle time of <b>' + c.newHandle.toFixed(2)
      + ' min/email</b> is derived from the L4/L3/L2 mix and the per-tier review times, '
      + 'not assumed. If the implied efficiency drifts more than 3 pp from the operational target, '
      + 'rebalance the mix or per-tier minutes until they converge. The mix here lands at <b>'
      + (c.impliedEff*100).toFixed(0) + '%</b> against a target of <b>' + (c.eff*100).toFixed(0) + '%</b>.';

    renderSens(c);
    renderScenarios(c);
    renderVs(c);
  }

  function renderVs(c) {
    const monthlyBenefit = c.cashSavings / 12;
    const zMonthlyRunCost = (c.platform + c.gov) / 12;
    const cMonthlyRunCost = (c.platform + c.competitorGov) / 12;
    const competitorRamp = c.competitorRampMonths;
    const competitorCap = c.competitorRealizationCap / 100;
    const cMonthlyBenefit = monthlyBenefit * competitorCap;
    const zSeries = simulateCum(c.zbrainStartMonth, c.rampMonths, monthlyBenefit, zMonthlyRunCost, c.impl, c.horizonMonths);
    const cSeries = simulateCum(c.competitorStartMonth, competitorRamp, cMonthlyBenefit, cMonthlyRunCost, c.competitorImpl, c.horizonMonths);

    const zPay = findPayback(zSeries);
    const cPay = findPayback(cSeries);
    const zEnd = zSeries[zSeries.length - 1].cum;
    const cEnd = cSeries[cSeries.length - 1].cum;
    const headStart = zEnd - cEnd;

    function cumAt(series, m) {
      return series[Math.min(m, series.length - 1)].cum;
    }
    const zY1 = cumAt(zSeries, 12) - cumAt(zSeries, 0);
    const cY1 = cumAt(cSeries, 12) - cumAt(cSeries, 0);
    const zY2 = cumAt(zSeries, 24) - cumAt(zSeries, 12);
    const cY2 = cumAt(cSeries, 24) - cumAt(cSeries, 12);
    const zY3 = cumAt(zSeries, 36) - cumAt(zSeries, 24);
    const cY3 = cumAt(cSeries, 36) - cumAt(cSeries, 24);

    const paybackDelta = (zPay != null && cPay != null) ? (cPay - zPay) : null;
    const zbrainStartWeeks = (c.zbrainStartMonth * 4.345);

    $("vsHeadline").innerHTML =
      '<div style="background:linear-gradient(135deg, #EAF1FF 0%, #E8F5EE 100%);'
      + 'border:1px solid #C9D8FB; border-radius:12px; padding:18px 22px; margin-bottom:18px;'
      + 'display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:18px;">'
      + '<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);font-weight:700;">Cumulative head start at m' + c.horizonMonths + '</div>'
      + '<div style="font-size:30px;font-weight:700;color:var(--accent);margin-top:6px;letter-spacing:-0.02em;">+' + fmShort(headStart) + '</div>'
      + '<div style="font-size:11.5px;color:var(--muted);margin-top:2px;">Extra cash that ZBrain delivers</div></div>'
      + '<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);font-weight:700;">Year-1 net cash flow</div>'
      + '<div style="font-size:30px;font-weight:700;color:var(--ok);margin-top:6px;letter-spacing:-0.02em;">' + fmShort(zY1) + '</div>'
      + '<div style="font-size:11.5px;color:var(--muted);margin-top:2px;">vs competitor ' + fmShort(cY1) + '</div></div>'
      + '<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);font-weight:700;">Time-to-value lead</div>'
      + '<div style="font-size:30px;font-weight:700;color:var(--ok);margin-top:6px;letter-spacing:-0.02em;">' + (c.competitorStartMonth - c.zbrainStartMonth).toFixed(1) + ' mo</div>'
      + '<div style="font-size:11.5px;color:var(--muted);margin-top:2px;">Earlier first value</div></div>'
      + '<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);font-weight:700;">Payback lead</div>'
      + '<div style="font-size:30px;font-weight:700;color:var(--warn);margin-top:6px;letter-spacing:-0.02em;">'
      + (paybackDelta != null ? paybackDelta.toFixed(1) + ' mo' : 'n/a') + '</div>'
      + '<div style="font-size:11.5px;color:var(--muted);margin-top:2px;">Earlier to break-even</div></div>'
      + '</div>';

    // Timeline (Gantt-style)
    const tlW = 1280, tlH = 200;
    const tlPad = { l: 130, r: 30, t: 30, b: 36 };
    const tlInner = tlW - tlPad.l - tlPad.r;
    const monthsMax = c.horizonMonths;
    function txS(m) { return tlPad.l + (m / monthsMax) * tlInner; }

    const zPhases = [
      { from: 0, to: c.zbrainStartMonth, label: "Build + UAT", color: "#1A55F9", opacity: 0.35 },
      { from: c.zbrainStartMonth, to: c.zbrainStartMonth + c.rampMonths, label: "V1 live, ramp", color: "#1A55F9", opacity: 0.65 },
      { from: c.zbrainStartMonth + c.rampMonths, to: monthsMax, label: "Steady state (100%)", color: "#1A55F9", opacity: 1.0 },
    ];
    const cPhases = [
      { from: 0, to: 2, label: "Discovery", color: "#C77700", opacity: 0.25 },
      { from: 2, to: c.competitorStartMonth, label: "Build + pilot", color: "#C77700", opacity: 0.45 },
      { from: c.competitorStartMonth, to: c.competitorStartMonth + competitorRamp, label: "Production rollout, ramp", color: "#C77700", opacity: 0.75 },
      { from: c.competitorStartMonth + competitorRamp, to: monthsMax, label: "Steady state (100%)", color: "#C77700", opacity: 1.0 },
    ];

    let tl = '<svg viewBox="0 0 ' + tlW + ' ' + tlH + '" preserveAspectRatio="xMidYMid meet" style="width:100%;background:#fff;">';
    // x axis ticks
    for (let m = 0; m <= monthsMax; m += 3) {
      const x = txS(m);
      tl += '<line x1="' + x + '" x2="' + x + '" y1="' + (tlH - tlPad.b) + '" y2="' + (tlH - tlPad.b + 4) + '" stroke="#9CA3AF" />';
      tl += '<text x="' + x + '" y="' + (tlH - tlPad.b + 18) + '" text-anchor="middle" font-size="10" fill="#6B7280" font-family="inherit">' + (m === 0 ? "Kickoff" : "Mo " + m) + '</text>';
    }
    // ZBrain row
    const zY0 = tlPad.t + 4;
    const rowH = 36;
    tl += '<text x="' + (tlPad.l - 10) + '" y="' + (zY0 + 22) + '" text-anchor="end" font-size="13" fill="#1A55F9" font-weight="700" font-family="inherit">ZBrain</text>';
    zPhases.forEach(function(p){
      const x = txS(p.from), w = txS(p.to) - txS(p.from);
      tl += '<rect x="' + x + '" y="' + zY0 + '" width="' + w + '" height="' + rowH + '" fill="' + p.color + '" fill-opacity="' + p.opacity + '" rx="3" />';
      if (w > 70) tl += '<text x="' + (x + w/2) + '" y="' + (zY0 + rowH/2 + 4) + '" text-anchor="middle" font-size="11" fill="white" font-weight="600" font-family="inherit">' + p.label + '</text>';
    });
    tl += '<circle cx="' + txS(c.zbrainStartMonth) + '" cy="' + (zY0 + rowH + 2) + '" r="5" fill="#1A55F9" stroke="white" stroke-width="2" />';
    tl += '<text x="' + txS(c.zbrainStartMonth) + '" y="' + (zY0 + rowH + 18) + '" text-anchor="middle" font-size="10" fill="#1A55F9" font-weight="700" font-family="inherit">First value &middot; wk ' + zbrainStartWeeks.toFixed(0) + '</text>';

    // Competitor row
    const cY0 = zY0 + rowH + 32;
    tl += '<text x="' + (tlPad.l - 10) + '" y="' + (cY0 + 22) + '" text-anchor="end" font-size="13" fill="#C77700" font-weight="700" font-family="inherit">Competitor</text>';
    cPhases.forEach(function(p){
      const x = txS(p.from), w = txS(p.to) - txS(p.from);
      tl += '<rect x="' + x + '" y="' + cY0 + '" width="' + w + '" height="' + rowH + '" fill="' + p.color + '" fill-opacity="' + p.opacity + '" rx="3" />';
      if (w > 70) tl += '<text x="' + (x + w/2) + '" y="' + (cY0 + rowH/2 + 4) + '" text-anchor="middle" font-size="11" fill="white" font-weight="600" font-family="inherit">' + p.label + '</text>';
    });
    tl += '<circle cx="' + txS(c.competitorStartMonth) + '" cy="' + (cY0 + rowH + 2) + '" r="5" fill="#C77700" stroke="white" stroke-width="2" />';
    tl += '<text x="' + txS(c.competitorStartMonth) + '" y="' + (cY0 + rowH + 18) + '" text-anchor="middle" font-size="10" fill="#C77700" font-weight="700" font-family="inherit">First value &middot; m' + c.competitorStartMonth + '</text>';
    tl += '</svg>';
    $("vsTimeline").innerHTML = tl;

    // Cumulative cash chart - enterprise palette, right-side bracket annotation
    const COLOR_Z = '#1E3A8A';     // navy-800
    const COLOR_C = '#64748B';     // slate-500
    const COLOR_ZONE = '#059669';  // emerald-600
    const COLOR_GRID = '#F1F5F9';  // slate-100
    const COLOR_AXIS = '#CBD5E1';  // slate-300
    const COLOR_LABEL = '#475569'; // slate-600
    const COLOR_HEADING = '#1E293B'; // slate-800

    const W = 1280, H = 460;
    const pad = { l: 88, r: 168, t: 64, b: 64 };
    const xW = W - pad.l - pad.r;
    const yH = H - pad.t - pad.b;
    const all = zSeries.concat(cSeries);
    const vMin = Math.min(0, ...all.map(function(p){return p.cum;}));
    const vMax = Math.max(0, ...all.map(function(p){return p.cum;}));
    function xS(m) { return pad.l + (m / c.horizonMonths) * xW; }
    function yS(v) { return pad.t + ((vMax - v) / (vMax - vMin || 1)) * yH; }

    function pathFor(series) {
      return series.map(function(p, i){
        return (i === 0 ? 'M' : 'L') + xS(p.month).toFixed(1) + ',' + yS(p.cum).toFixed(1);
      }).join(' ');
    }
    const zPath = pathFor(zSeries);
    const cPath = pathFor(cSeries);
    const cBackward = cSeries.slice().reverse().map(function(p){
      return 'L' + xS(p.month).toFixed(1) + ',' + yS(p.cum).toFixed(1);
    }).join(' ');
    const gapArea = zPath + ' ' + cBackward + ' Z';
    const zeroY = yS(0);

    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" style="width:100%;background:#fff;font-family:inherit;">';

    // Defs (gradient for advantage zone)
    svg += '<defs>';
    svg += '<linearGradient id="zoneGrad" x1="0" y1="0" x2="0" y2="1">';
    svg += '<stop offset="0%" stop-color="' + COLOR_ZONE + '" stop-opacity="0.22"/>';
    svg += '<stop offset="100%" stop-color="' + COLOR_ZONE + '" stop-opacity="0.05"/>';
    svg += '</linearGradient>';
    svg += '</defs>';

    // Top legend (refined, top-left)
    const legY = pad.t - 30;
    svg += '<g>';
    svg += '<line x1="' + pad.l + '" x2="' + (pad.l + 22) + '" y1="' + legY + '" y2="' + legY + '" stroke="' + COLOR_Z + '" stroke-width="2.5" />';
    svg += '<text x="' + (pad.l + 28) + '" y="' + (legY + 4) + '" font-size="12" fill="' + COLOR_HEADING + '" font-weight="600">ZBrain</text>';
    svg += '<text x="' + (pad.l + 76) + '" y="' + (legY + 4) + '" font-size="11" fill="' + COLOR_LABEL + '">V1 live at week ' + zbrainStartWeeks.toFixed(0) + '</text>';

    svg += '<line x1="' + (pad.l + 220) + '" x2="' + (pad.l + 242) + '" y1="' + legY + '" y2="' + legY + '" stroke="' + COLOR_C + '" stroke-width="2" stroke-dasharray="5,3" />';
    svg += '<text x="' + (pad.l + 248) + '" y="' + (legY + 4) + '" font-size="12" fill="' + COLOR_HEADING + '" font-weight="600">Competitor</text>';
    svg += '<text x="' + (pad.l + 322) + '" y="' + (legY + 4) + '" font-size="11" fill="' + COLOR_LABEL + '">first value Mo ' + c.competitorStartMonth + '</text>';

    svg += '<rect x="' + (pad.l + 442) + '" y="' + (legY - 6) + '" width="22" height="11" fill="url(#zoneGrad)" stroke="' + COLOR_ZONE + '" stroke-width="0.8" />';
    svg += '<text x="' + (pad.l + 470) + '" y="' + (legY + 4) + '" font-size="12" fill="' + COLOR_HEADING + '" font-weight="600">ZBrain head-start zone</text>';
    svg += '</g>';

    // Y-axis gridlines + tick labels
    const yTicks = [];
    const range = vMax - vMin || 1;
    const niceStep = function() {
      const rough = range / 5;
      const mag = Math.pow(10, Math.floor(Math.log10(rough)));
      const norm = rough / mag;
      if (norm < 1.5) return mag;
      if (norm < 3) return 2 * mag;
      if (norm < 7) return 5 * mag;
      return 10 * mag;
    }();
    for (let v = Math.ceil(vMin/niceStep)*niceStep; v <= vMax; v += niceStep) yTicks.push(v);
    if (yTicks.indexOf(0) === -1) yTicks.push(0);
    yTicks.forEach(function(v){
      const y = yS(v);
      svg += '<line x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + y + '" y2="' + y + '" stroke="' + COLOR_GRID + '" stroke-width="1" />';
      svg += '<text x="' + (pad.l - 12) + '" y="' + (y + 4) + '" text-anchor="end" font-size="11" fill="' + COLOR_LABEL + '" font-weight="500">' + fmShort(v) + '</text>';
    });

    // Zero / break-even line (more subtle)
    svg += '<line x1="' + pad.l + '" x2="' + (W - pad.r) + '" y1="' + zeroY + '" y2="' + zeroY + '" stroke="#94A3B8" stroke-dasharray="3,3" stroke-width="1" />';

    // X-axis ticks with Year markers
    for (let m = 0; m <= c.horizonMonths; m += 3) {
      const x = xS(m);
      const isYearBoundary = (m > 0 && m % 12 === 0);
      svg += '<line x1="' + x + '" x2="' + x + '" y1="' + (H - pad.b) + '" y2="' + (H - pad.b + (isYearBoundary ? 7 : 4)) + '" stroke="' + COLOR_AXIS + '" stroke-width="' + (isYearBoundary ? 1.5 : 1) + '" />';
      const label = m === 0 ? "Kickoff" : (m === 12 ? "Year 1" : (m === 24 ? "Year 2" : (m === 36 ? "Year 3" : "M" + m)));
      svg += '<text x="' + x + '" y="' + (H - pad.b + 22) + '" text-anchor="middle" font-size="11" fill="' + COLOR_LABEL + '" font-weight="' + (isYearBoundary ? 700 : 500) + '">' + label + '</text>';
    }
    svg += '<text x="' + ((pad.l + W - pad.r)/2) + '" y="' + (H - 14) + '" text-anchor="middle" font-size="10.5" fill="' + COLOR_LABEL + '" font-style="italic" letter-spacing="0.03em">Months from project kickoff</text>';

    // Advantage zone (gradient fill, no stroke)
    svg += '<path d="' + gapArea + '" fill="url(#zoneGrad)" stroke="none" />';

    // Competitor line (drawn first, behind ZBrain)
    svg += '<path d="' + cPath + '" fill="none" stroke="' + COLOR_C + '" stroke-width="2" stroke-dasharray="6,4" />';
    // ZBrain line (foreground)
    svg += '<path d="' + zPath + '" fill="none" stroke="' + COLOR_Z + '" stroke-width="2.75" />';

    // Payback markers
    if (zPay != null) {
      svg += '<circle cx="' + xS(zPay) + '" cy="' + zeroY + '" r="4.5" fill="' + COLOR_Z + '" stroke="white" stroke-width="2" />';
      svg += '<text x="' + xS(zPay) + '" y="' + (zeroY - 12) + '" text-anchor="middle" font-size="10.5" fill="' + COLOR_Z + '" font-weight="600">ZBrain break-even &middot; Mo ' + zPay.toFixed(1) + '</text>';
    }
    if (cPay != null) {
      svg += '<circle cx="' + xS(cPay) + '" cy="' + zeroY + '" r="4.5" fill="' + COLOR_C + '" stroke="white" stroke-width="2" />';
      svg += '<text x="' + xS(cPay) + '" y="' + (zeroY + 19) + '" text-anchor="middle" font-size="10.5" fill="' + COLOR_C + '" font-weight="600">Competitor break-even &middot; Mo ' + cPay.toFixed(1) + '</text>';
    }

    // Right-side bracket annotation showing gap at horizon
    const xEnd = xS(c.horizonMonths);
    const yZEnd = yS(zEnd);
    const yCEnd = yS(cEnd);
    const bracketX = xEnd + 14;
    const labelX = bracketX + 10;
    const gap = zEnd - cEnd;

    // Thin leader lines from each curve end to the bracket
    svg += '<line x1="' + xEnd + '" x2="' + bracketX + '" y1="' + yZEnd + '" y2="' + yZEnd + '" stroke="' + COLOR_Z + '" stroke-width="1.25" />';
    svg += '<line x1="' + xEnd + '" x2="' + bracketX + '" y1="' + yCEnd + '" y2="' + yCEnd + '" stroke="' + COLOR_C + '" stroke-width="1.25" />';

    // Bracket
    svg += '<line x1="' + bracketX + '" x2="' + bracketX + '" y1="' + yZEnd + '" y2="' + yCEnd + '" stroke="' + COLOR_ZONE + '" stroke-width="2.25" />';
    svg += '<line x1="' + bracketX + '" x2="' + (bracketX + 5) + '" y1="' + yZEnd + '" y2="' + yZEnd + '" stroke="' + COLOR_ZONE + '" stroke-width="2.25" />';
    svg += '<line x1="' + bracketX + '" x2="' + (bracketX + 5) + '" y1="' + yCEnd + '" y2="' + yCEnd + '" stroke="' + COLOR_ZONE + '" stroke-width="2.25" />';

    // End-of-horizon labels (right of bracket)
    svg += '<text x="' + labelX + '" y="' + (yZEnd - 6) + '" font-size="10" fill="' + COLOR_LABEL + '" font-weight="600" letter-spacing="0.06em">ZBRAIN</text>';
    svg += '<text x="' + labelX + '" y="' + (yZEnd + 9) + '" font-size="14" fill="' + COLOR_Z + '" font-weight="700">' + fmShort(zEnd) + '</text>';

    svg += '<text x="' + labelX + '" y="' + (yCEnd - 6) + '" font-size="10" fill="' + COLOR_LABEL + '" font-weight="600" letter-spacing="0.06em">COMPETITOR</text>';
    svg += '<text x="' + labelX + '" y="' + (yCEnd + 9) + '" font-size="14" fill="' + COLOR_C + '" font-weight="700">' + fmShort(cEnd) + '</text>';

    // Gap label (vertical center between the two ends)
    const midY = (yZEnd + yCEnd) / 2;
    svg += '<text x="' + labelX + '" y="' + (midY - 3) + '" font-size="9.5" fill="' + COLOR_ZONE + '" font-weight="700" letter-spacing="0.08em">36-MO GAP</text>';
    svg += '<text x="' + labelX + '" y="' + (midY + 11) + '" font-size="13.5" fill="' + COLOR_ZONE + '" font-weight="700">+' + fmShort(gap) + '</text>';

    svg += '</svg>';
    $("vsChart").innerHTML = svg;

    // Assumptions block
    const sameImpl = (c.impl === c.competitorImpl);
    const sameGov = (c.gov === c.competitorGov);
    const zY1Pct = (zY1 / (c.cashSavings - (c.platform + c.gov)) * 100);
    const cY1Pct = (cY1 / (c.cashSavings - (c.platform + c.gov)) * 100);
    const assumptions = [
      ["ZBrain V1 in production", "Week " + zbrainStartWeeks.toFixed(0) + " (accelerated build, pilot, UAT)"],
      ["Competitor first value", "Month " + c.competitorStartMonth + " (typical tier-1 SI: discovery 2 mo, build + pilot " + (c.competitorStartMonth - 2) + " mo)"],
      ["Ramp duration &middot; ZBrain", c.rampMonths + " months linear 0 to 100% of steady-state"],
      ["Ramp duration &middot; Competitor", competitorRamp.toFixed(0) + " months linear 0 to cap"],
      ["Steady-state realization cap &middot; ZBrain", "100% (mature platform, continuous learning, rapid iteration)"],
      ["Steady-state realization cap &middot; Competitor", c.competitorRealizationCap.toFixed(0) + "% (matches ZBrain at the ceiling; the head-start gap is driven by slower ramp, not a lower cap)"],
      ["Year-1 realized benefit &middot; ZBrain", zY1Pct.toFixed(0) + "% of steady-state run rate (8-week first value, 6-month ramp)"],
      ["Year-1 realized benefit &middot; Competitor", cY1Pct.toFixed(0) + "% of steady-state run rate (month-6 first value, " + competitorRamp.toFixed(0) + "-month ramp, " + c.competitorRealizationCap.toFixed(0) + "% cap)"],
      ["Implementation cost &middot; ZBrain", fm(c.impl) + " upfront"],
      ["Implementation cost &middot; Competitor", fm(c.competitorImpl) + (sameImpl ? " (matches ZBrain; edit to differ)" : " upfront")],
      ["Annual run cost &middot; ZBrain", fm(c.platform) + " platform + " + fm(c.gov) + " support &amp; governance"],
      ["Annual run cost &middot; Competitor", fm(c.platform) + " platform + " + fm(c.competitorGov) + " support &amp; governance" + (sameGov ? " (matches ZBrain; edit to differ)" : "")],
      ["Annual cash benefit (full)", fm(c.cashSavings) + " (FTE released x cost, x " + (c.redeploy*100).toFixed(0) + "% redeployment)"],
      ["Comparison horizon", c.horizonMonths + " months"],
      ["Conservatism vs main case", "Main Section 2 uses 55%/95%/100% Year-1/2/3 realization haircut on top. This view shows time-to-value directly."],
    ];
    $("vsAssumptions").innerHTML = assumptions.map(function(a){
      return '<div class="row" style="grid-template-columns: 1fr 1.3fr;">'
           + '<div class="lbl">' + a[0] + '</div>'
           + '<div class="v" style="text-align:left;font-weight:500;color:#374151;">' + a[1] + '</div></div>';
    }).join("");

    const rows = [
      ["Time to first value", zbrainStartWeeks.toFixed(0) + " weeks", c.competitorStartMonth + " months"],
      ["Payback (months from kickoff)", zPay != null ? zPay.toFixed(1) : "n/a", cPay != null ? cPay.toFixed(1) : "n/a"],
      ["Year-1 net cash flow", fmShort(zY1), fmShort(cY1)],
      ["Year-2 net cash flow", fmShort(zY2), fmShort(cY2)],
      ["Year-3 net cash flow", fmShort(zY3), fmShort(cY3)],
      ["Cumulative cash at m" + c.horizonMonths, fmShort(zEnd), fmShort(cEnd)],
    ];
    let tbl = '<table class="yeartable" style="margin-top:6px;"><thead><tr>'
            + '<th>Metric</th><th style="text-align:right;color:#1A55F9;">ZBrain</th>'
            + '<th style="text-align:right;color:#C77700;">Competitor</th><th style="text-align:right;">Delta</th></tr></thead><tbody>';
    rows.forEach(function(r, i){
      let delta = "&middot;";
      if (i === 0) delta = (c.competitorStartMonth - c.zbrainStartMonth).toFixed(1) + " mo earlier";
      else if (i === 1 && zPay != null && cPay != null) delta = (cPay - zPay).toFixed(1) + " mo earlier";
      else if (i >= 2) {
        const zv = [zY1, zY2, zY3, zEnd][i-2];
        const cv = [cY1, cY2, cY3, cEnd][i-2];
        delta = '<span style="color:var(--ok)">+' + fmShort(zv - cv) + '</span>';
      }
      tbl += '<tr><td>' + r[0] + '</td><td style="text-align:right;color:#1A55F9;font-weight:600;">' + r[1] + '</td>'
           + '<td style="text-align:right;color:#C77700;">' + r[2] + '</td>'
           + '<td style="text-align:right;font-weight:600;">' + delta + '</td></tr>';
    });
    tbl += '</tbody></table>';
    $("vsTable").innerHTML = tbl;

    $("vsNarrative").innerHTML =
      '<b>Year-1 reading:</b> ZBrain delivers <b>' + fmShort(zY1) + '</b> of net cash flow in Year 1 against the competitor\'s <b>'
      + fmShort(cY1) + '</b>. The ZBrain Year-1 number is the time-derived ' + (zY1 / (c.cashSavings - c.annualSolutionCost) * 100).toFixed(0)
      + '% realization of the steady-state run rate, driven by the week ' + zbrainStartWeeks.toFixed(0)
      + ' first value + ' + c.rampMonths + '-month ramp. The conservative 55% Year-1 figure used in Section 2 sits below this, providing a risk buffer. '
      + 'The ' + (c.competitorStartMonth - c.zbrainStartMonth).toFixed(1) + '-month time-to-value lead plus the slower competitor ramp '
      + 'compounds into a <b>' + fmShort(headStart) + '</b> cumulative cash advantage by month ' + c.horizonMonths + '.';
  }

  function renderSens(c) {
    const effRange = [60, 62, 65, 68, 70];
    const fteRange = [10000, 12500, 15000, 17500, 20000];
    let h = '<thead><tr><th>FTE cost \\ Efficiency</th>';
    effRange.forEach(function(e){ h += '<th>' + e + '%</th>'; });
    h += '</tr></thead><tbody>';
    fteRange.forEach(function(fc){
      h += '<tr><td><b>' + fm(fc) + '</b></td>';
      effRange.forEach(function(e){
        const eff = e/100;
        const gross = c.ftes * fc * eff;
        const cash = gross * c.redeploy;
        const y1 = cash * c.y1R - c.platform - c.gov - c.impl;
        const y2 = cash * c.y2R - c.platform - c.gov;
        const y3 = cash * c.y3R - c.platform - c.gov;
        const npv = y1/(1+c.disc) + y2/Math.pow(1+c.disc,2) + y3/Math.pow(1+c.disc,3);
        const isDef = (e === 65 && fc === 15000);
        const style = isDef ? 'style="background:var(--accent-soft);font-weight:700;color:var(--accent);"' : '';
        h += '<td ' + style + '>' + fmShort(npv) + '</td>';
      });
      h += '</tr>';
    });
    h += '</tbody>';
    $("sensTable").innerHTML = h;
  }

  function renderScenarios(c) {
    const scenarios = [
      ["Conservative", 0.60, 600, 0.60, "Year-1 pilot only, low FTE pool"],
      ["Base (proposal)", 0.65, 650, 0.70, "Mid-range FTE pool, 65% efficiency"],
      ["Aggressive", 0.70, 700, 0.80, "Full team, top of efficiency band"],
    ];
    $("scenarioBreakdown").innerHTML = scenarios.map(function(arr){
      const name=arr[0], eff=arr[1], fte=arr[2], rd=arr[3], desc=arr[4];
      const gross = fte * c.costPerFte * eff;
      const cash = gross * rd;
      const net = cash - c.platform - c.gov;
      const y1 = cash * c.y1R - c.platform - c.gov - c.impl;
      const y2 = cash * c.y2R - c.platform - c.gov;
      const y3 = cash * c.y3R - c.platform - c.gov;
      const npv = y1/(1+c.disc) + y2/Math.pow(1+c.disc,2) + y3/Math.pow(1+c.disc,3);
      return '<div class="row" style="grid-template-columns: 1fr 140px 140px;"><div class="lbl"><b>'
           + name + '</b><span class="h">' + desc + '</span></div>'
           + '<div class="v" style="color:var(--ok)">' + fmShort(net) + ' / yr</div>'
           + '<div class="v" style="color:var(--accent)">' + fmShort(npv) + ' NPV</div></div>';
    }).join("");
  }

  function compute_and_render() { render(compute()); }

  window.selectTab = function(name) {
    document.querySelectorAll('.tab').forEach(function(t){
      t.classList.toggle('active', t.getAttribute('data-tab') === name);
    });
    document.querySelectorAll('.tab-panel').forEach(function(p){
      p.classList.toggle('active', p.id === 'tab-' + name);
    });
  };

  window.resetBenefit = function() {
    userOverrode = false;
    for (const k in DEFAULTS) {
      const el = document.getElementById(k);
      if (el) el.value = DEFAULTS[k];
    }
    compute_and_render();
    if (window.__syncBenefit) window.__syncBenefit();
  };

  document.addEventListener("DOMContentLoaded", function() {
    for (const k in DEFAULTS) {
      const el = document.getElementById(k);
      if (!el) continue;
      if (k === "platformCost") {
        el.addEventListener("input", function() { userOverrode = true; el.classList.remove("linked"); compute_and_render(); });
      } else {
        el.addEventListener("input", compute_and_render);
      }
    }
    compute_and_render();
  });
})();
</script>
</body>
</html>
"""

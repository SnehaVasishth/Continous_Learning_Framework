"""Customer-perspective value-capture calculator served at
/api/docs/rfp-reply/value-capture.

This is the third in the calculator family:
  - benefit-case         → full calculator (30+ inputs, 3-year NPV)
  - benefit-case-simple  → 6-input customer-friendly version
  - value-capture        → THIS: time-to-value comparison

Frame: customer pays ZBrain for a defined engagement window (default
22 weeks). ZBrain is live by week 8; every week after that is FTE-cost
they would otherwise be spending. A typical SI delivers in 6 months and
captures zero value inside that window. Even though ZBrain's cost over
the window is higher than the SI's fixed-price implementation, the
customer is meaningfully ahead at the contract end because they're
recovering money they would otherwise be spending on FTE inefficiency.

Minimal by design: four inputs, four headline numbers, one comparison
block. Same visual family as the other two calculators so a buyer can
flip between them without re-orienting."""

BENEFIT_CALCULATOR_VALUE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Keysight SalesOps · Value capture · ZBrain</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    --ink: #131426; --muted: #6B7280; --rule: #E5E7EB; --surface: #F8FAFC;
    --accent: #1A55F9; --accent-soft: #1A55F910;
    --ok: #1F8A4C; --ok-soft: #E1F4E8;
    --warn: #C77700; --warn-soft: #FEF3C7;
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
  .cover p { font-size: 14.5px; max-width: 920px; color: #C7CEE2; margin: 0;
             line-height: 1.6; }
  .cover h1, .cover p, .cover .eyebrow { position: relative; z-index: 1; }

  /* ---------- Headline tiles ---------- */
  .headline {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
    margin: 0 0 26px;
  }
  @media (max-width: 1000px) { .headline { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 560px)  { .headline { grid-template-columns: 1fr; } }
  .hl {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 18px 20px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
  }
  .hl .lbl {
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.12em;
    color: var(--muted); font-weight: 700;
  }
  .hl .val {
    font-size: 30px; font-weight: 700; color: var(--ink);
    font-variant-numeric: tabular-nums; margin-top: 6px;
    letter-spacing: -0.02em;
  }
  .hl .sub { font-size: 11.5px; color: var(--muted); margin-top: 4px; line-height: 1.5; }
  .hl.accent { background: linear-gradient(180deg, #EAF1FF, white 70%); border-color: #C9D8FB; }
  .hl.accent .lbl { color: var(--accent); }
  .hl.accent .val { color: var(--accent); }
  .hl.ok     { background: linear-gradient(180deg, #E8F5EE, white 70%); border-color: #B9DEC8; }
  .hl.ok     .val { color: var(--ok); }
  .hl.rose   { background: linear-gradient(180deg, #FEECEC, white 70%); border-color: #F5C2C2; }
  .hl.rose   .val { color: var(--rose); }

  /* ---------- Math breakdown ---------- */
  .math-card {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 20px 24px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
    margin-bottom: 26px;
  }
  .math-card h2 { font-size: 15px; margin: 0 0 12px; letter-spacing: -0.01em; }
  .math-line {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 7px 0; border-top: 1px dashed var(--rule);
    font-size: 13px;
  }
  .math-line:first-child { border-top: none; }
  .math-line span:first-child { color: var(--muted); }
  .math-line .math-eq {
    font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 12.5px; color: var(--ink);
  }
  .math-line.emph { background: #F5F7FF; border-radius: 6px; padding: 8px 10px; border-top: none; }
  .math-line.emph span:first-child { color: var(--accent); font-weight: 600; }
  .math-line.emph .math-eq b { color: var(--accent); }
  .math-section {
    margin-top: 14px; padding: 6px 0 4px;
    font-size: 11px; font-weight: 700;
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em;
  }
  .math-foot {
    margin-top: 12px; padding-top: 10px;
    border-top: 1px dashed var(--rule);
    font-size: 11.5px; color: var(--muted);
  }

  /* ---------- Inputs panel ---------- */
  .panel {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 22px 24px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
    margin-bottom: 26px;
  }
  .panel h2 { font-size: 16px; margin: 0 0 4px; letter-spacing: -0.01em; }
  .panel .h2sub { font-size: 12.5px; color: var(--muted); margin: 0 0 18px; }
  .inputs {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
  }
  @media (max-width: 1000px) { .inputs { grid-template-columns: repeat(2, 1fr); } }
  .input-row label {
    display: flex; flex-direction: column; gap: 2px;
    font-size: 12.5px; color: var(--ink); font-weight: 500;
  }
  .input-row label .hint { font-size: 11px; color: var(--muted); font-weight: 400; }
  .input-row .field {
    display: flex; align-items: stretch; margin-top: 6px;
    border: 1px solid var(--rule); border-radius: 8px; overflow: hidden;
    background: white; transition: border-color .12s, box-shadow .12s;
  }
  .input-row .field:focus-within {
    border-color: var(--accent); box-shadow: 0 0 0 3px rgba(26,85,249,0.12);
  }
  .input-row .field .pre, .input-row .field .post {
    display: inline-flex; align-items: center; padding: 0 9px;
    color: var(--muted); font-size: 12.5px; background: var(--surface);
  }
  .input-row .field input {
    flex: 1; min-width: 0; padding: 9px 11px;
    border: none; outline: none; background: white;
    color: var(--ink); font-size: 14px;
    font-variant-numeric: tabular-nums; text-align: right;
  }

  /* ---------- Timeline visualization ---------- */
  .timeline-card {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 22px 24px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
    margin-bottom: 26px;
  }
  .timeline-card h2 { font-size: 16px; margin: 0 0 4px; }
  .timeline-card .h2sub { font-size: 12.5px; color: var(--muted); margin: 0 0 20px; }
  .tl-row {
    display: grid; grid-template-columns: 100px 1fr 140px; gap: 14px;
    align-items: center; margin-bottom: 12px;
  }
  .tl-row .who {
    font-size: 12.5px; font-weight: 600; color: var(--ink);
  }
  .tl-row .who small {
    display: block; font-size: 10.5px; color: var(--muted); font-weight: 500; margin-top: 1px;
  }
  .tl-bar {
    position: relative;
    height: 38px;
    background: var(--surface);
    border-radius: 6px;
    border: 1px solid var(--rule);
    overflow: hidden;
  }
  .tl-build {
    position: absolute; top: 0; bottom: 0; left: 0;
    background: linear-gradient(180deg, #DDE7FB, #C5D5F8);
    border-right: 2px solid #6E8AE8;
    display: flex; align-items: center; justify-content: center;
    color: #2C3E73; font-size: 11px; font-weight: 600;
    letter-spacing: 0.02em;
  }
  .tl-live {
    position: absolute; top: 0; bottom: 0;
    background: linear-gradient(180deg, #C6ECD3, #A6DDB6);
    border-right: 2px solid #1F8A4C;
    display: flex; align-items: center; justify-content: center;
    color: #1F8A4C; font-size: 11px; font-weight: 600;
  }
  .tl-pending {
    position: absolute; top: 0; bottom: 0;
    background: repeating-linear-gradient(45deg,
      var(--rose-soft), var(--rose-soft) 6px,
      #FBE0E0 6px, #FBE0E0 12px);
    border-right: 2px dashed var(--rose);
    display: flex; align-items: center; justify-content: center;
    color: var(--rose); font-size: 11px; font-weight: 600;
  }
  .tl-marker {
    position: absolute; top: 0; bottom: 0;
    width: 0; border-left: 2px dashed rgba(17, 24, 39, 0.55);
    pointer-events: none;
  }
  .tl-marker-lbl {
    position: absolute; top: -16px; transform: translateX(-50%);
    font-size: 9.5px; color: rgba(17, 24, 39, 0.65);
    white-space: nowrap; font-weight: 600;
    letter-spacing: 0.02em;
  }
  .tl-ticks {
    display: grid; grid-template-columns: 100px 1fr 140px; gap: 14px;
    margin-top: 4px;
  }
  .tl-ticks .who-empty { }
  .tl-ticks .tick-bar {
    display: flex; justify-content: space-between;
    font-size: 10px; color: var(--muted);
  }
  .tl-ticks .tick-end { }
  .tl-row .savings {
    text-align: right; font-variant-numeric: tabular-nums;
  }
  .tl-row .savings .v {
    font-size: 18px; font-weight: 700; letter-spacing: -0.01em;
  }
  .tl-row .savings .l {
    font-size: 10.5px; color: var(--muted); margin-top: 1px;
    text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700;
  }
  .tl-row.zbrain .savings .v { color: var(--ok); }
  .tl-row.comp .savings .v { color: var(--rose); }

  /* ---------- Comparison block ---------- */
  .compare {
    background: white; border: 1px solid var(--rule); border-radius: 14px;
    padding: 24px 28px; box-shadow: 0 1px 2px rgba(0,0,0,.03);
    margin-bottom: 26px;
  }
  .compare h2 { font-size: 16px; margin: 0 0 4px; letter-spacing: -0.01em; }
  .compare .sub { font-size: 12.5px; color: var(--muted); margin: 0 0 18px; }
  .vs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
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
    background: linear-gradient(180deg, #FBFAF8, white 70%);
  }
  .vs .col .name {
    font-size: 13px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.12em;
    display: flex; align-items: center; gap: 8px;
  }
  .vs .col.zbrain .name { color: var(--accent); }
  .vs .col .name .dot {
    width: 8px; height: 8px; border-radius: 50%; background: var(--muted);
  }
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
  .vs .col.zbrain .row.lead .v { color: var(--accent); font-size: 17px; }
  .vs .col.comp   .row.lead .v { color: var(--rose); font-size: 17px; }
  .vs .col .row.sublbl { padding: 6px 0 6px 12px; }
  .vs .col .row.sublbl .k { font-size: 11.5px; color: var(--muted); }
  .vs .col .row.sublbl .v { font-size: 13px; font-weight: 500; color: var(--ink); }

  .compare .takeaway {
    margin-top: 18px; padding: 14px 18px;
    background: #F5F7FF; border-left: 4px solid var(--accent);
    border-radius: 8px;
    font-size: 13.5px; line-height: 1.6; color: var(--ink);
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
    .cover, .compare, .timeline-card, .panel { box-shadow: none; }
  }
</style>
</head>
<body>
<div class="shell">

  <div class="cover">
    <div class="eyebrow">Keysight Project · SalesOps Automation</div>
    <h1>Value capture, not implementation cost</h1>
    <p>
      ZBrain goes live in <strong>8 weeks</strong>; a typical systems integrator delivers in 6 months.
      That 16-week head start is real money you keep instead of spending on FTE inefficiency.
      Inputs are configurable below.
    </p>
  </div>

  <!-- Headline tiles -->
  <div class="headline">
    <div class="hl accent">
      <div class="lbl">Time to first live case</div>
      <div class="val" id="hlZbrainWeeks">8 wks</div>
      <div class="sub" id="hlVsCompetitor">vs typical SI: 24 weeks</div>
    </div>
    <div class="hl">
      <div class="lbl">Steady-state savings rate</div>
      <div class="val" id="hlSavingsRate">--</div>
      <div class="sub" id="hlGoLiveRate">go-live rate: --</div>
      <div class="sub" id="hlFtesRedeployed" style="margin-top:2px">--</div>
    </div>
    <div class="hl ok">
      <div class="lbl" id="hlZbrainRecoveredLbl">Recovered at engagement end · ZBrain</div>
      <div class="val" id="hlZbrainRecovered">--</div>
      <div class="sub" id="hlZbrainLiveWeeks">--</div>
    </div>
    <div class="hl accent">
      <div class="lbl" id="hlAdvantageLbl">ZBrain advantage at engagement end</div>
      <div class="val" id="hlAdvantage">--</div>
      <div class="sub" id="hlAdvantageSub">net position vs SI alternative</div>
    </div>
  </div>

  <!-- Timeline visualization -->
  <div class="timeline-card">
    <h2 id="tlTitle">Build vs live timeline</h2>
    <p class="h2sub">
      Blue is build (no savings yet). Green is live (capturing FTE cost). The bar runs from
      kickoff to SI go-live, the head-to-head moment.
    </p>

    <div class="tl-row zbrain">
      <div class="who">ZBrain<small id="tlZbrainSub">--</small></div>
      <div class="tl-bar" id="tlZbrain"></div>
      <div class="savings">
        <div class="v" id="tlZbrainSavings">--</div>
        <div class="l">captured by SI go-live</div>
      </div>
    </div>

    <div class="tl-row comp">
      <div class="who">SI alternative<small id="tlCompSub">--</small></div>
      <div class="tl-bar" id="tlComp"></div>
      <div class="savings">
        <div class="v" id="tlCompSavings">--</div>
        <div class="l">captured by SI go-live</div>
      </div>
    </div>

    <div class="tl-ticks">
      <div class="who-empty"></div>
      <div class="tick-bar">
        <span>Week 1</span><span>Week 8 · ZBrain live</span><span id="tlEndTick">Week 24 · SI go-live</span>
      </div>
      <div class="tick-end"></div>
    </div>
  </div>
<!-- Comparison block -->
  <div class="compare">
    <h2>Head-to-head at SI go-live</h2>
    <p class="sub">
      The SI's go-live week is the head-to-head moment. ZBrain has been live the whole way;
      the SI is starting from zero. Cost lines are itemised identically on both sides so the
      only thing moving the gap is time-in-market.
    </p>

    <div class="vs">
      <div class="col zbrain">
        <div class="name"><span class="dot"></span> ZBrain · 8-week delivery</div>
        <div class="row"><span class="k">Time to first production case</span><span class="v">8 weeks</span></div>

        <div class="row" style="border-top:2px solid var(--accent);background:rgba(26,85,249,0.04);padding-left:6px;padding-right:6px;border-radius:4px;margin-top:8px"><span class="k" style="font-weight:700;color:var(--accent)" id="vsZbrainEndLbl">At SI go-live</span><span class="v"></span></div>
        <div class="row"><span class="k">Weeks live</span><span class="v" id="vsZbrainLiveDec">--</span></div>
        <div class="row sublbl"><span class="k">Implementation</span><span class="v" id="vsZbrainImplH1">--</span></div>
        <div class="row sublbl"><span class="k">Platform run</span><span class="v" id="vsZbrainRunH1">--</span></div>
        <div class="row sublbl"><span class="k">Hypercare</span><span class="v" id="vsZbrainHyperH1">--</span></div>
        <div class="row"><span class="k">Total investment</span><span class="v" id="vsZbrainCostDec">--</span></div>
        <div class="row"><span class="k">FTE cost recovered</span><span class="v" id="vsZbrainRecoveredDec">--</span></div>
        <div class="row lead"><span class="k">Net position</span><span class="v" id="vsZbrainNetDec">--</span></div>
      </div>

      <div class="col comp">
        <div class="name"><span class="dot"></span> Systems-integrator alternative</div>
        <div class="row"><span class="k">Time to first production case</span><span class="v">
          <input type="number" id="compWeeks" value="24" min="8" max="104" step="1"
            style="width:54px;padding:3px 6px;border:1px solid var(--rule);border-radius:6px;font-size:14px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;" /> weeks
        </span></div>

        <div class="row" style="border-top:2px solid var(--rule);background:var(--surface);padding-left:6px;padding-right:6px;border-radius:4px;margin-top:8px"><span class="k" style="font-weight:700;color:var(--ink)" id="vsCompEndLbl">At SI go-live</span><span class="v"></span></div>
        <div class="row"><span class="k">Weeks live</span><span class="v" id="vsCompLiveDec">0</span></div>
        <div class="row sublbl"><span class="k">Fixed-price delivery</span><span class="v">
          $<input type="number" id="compInvest" value="800000" min="0" step="10000"
            style="width:108px;padding:3px 6px;border:1px solid var(--rule);border-radius:6px;font-size:14px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums;" />
        </span></div>
        <div class="row sublbl"><span class="k">Platform run</span><span class="v" id="vsCompRunH1">$0</span></div>
        <div class="row sublbl"><span class="k">Hypercare</span><span class="v" id="vsCompHyperH1">$0</span></div>
        <div class="row"><span class="k">Total investment</span><span class="v" id="vsCompTotalH1">--</span></div>
        <div class="row"><span class="k">FTE cost recovered</span><span class="v" id="vsCompRecoveredDec">$0</span></div>
        <div class="row lead"><span class="k">Net position</span><span class="v" id="vsCompNetDec">--</span></div>
      </div>
    </div>

    <div class="takeaway" id="takeaway"></div>
  </div>
<!-- Inputs -->
  <div class="panel">
    <h2>Inputs</h2>
    <div class="inputs">
      <div class="input-row">
        <label>
          CSR team in scope (FTE)
          <span class="hint">Headcount the workflow supports today</span>
        </label>
        <div class="field"><input type="number" id="ftes" value="650" min="0" step="10" /></div>
      </div>
      <div class="input-row">
        <label>
          Fully-loaded cost per FTE
          <span class="hint">Annual cost incl. benefits + overhead</span>
        </label>
        <div class="field"><span class="pre">$</span><input type="number" id="costPerFte" value="20000" min="0" step="500" /></div>
      </div>
      <div class="input-row">
        <label>
          Steady-state efficiency
          <span class="hint">Handle-time the workflow removes at maturity</span>
        </label>
        <div class="field"><input type="number" id="efficiency" value="70" min="0" max="95" step="1" /><span class="post">%</span></div>
      </div>
      <div class="input-row">
        <label>
          Efficiency at go-live (week 8)
          <span class="hint">Linear ramp to steady-state by engagement end</span>
        </label>
        <div class="field"><input type="number" id="goLiveEff" value="30" min="0" max="95" step="1" /><span class="post">%</span></div>
      </div>
      <div class="input-row">
        <label>
          ZBrain implementation (one-time)
          <span class="hint">Covers weeks 1 to engagement end</span>
        </label>
        <div class="field"><span class="pre">$</span><input type="number" id="zbrainImpl" value="1350000" min="0" step="50000" /></div>
      </div>
      <div class="input-row">
        <label>
          Platform run cost
          <span class="hint">Model + infra. Starts at go-live, week 9.</span>
        </label>
        <div class="field"><span class="pre">$</span><input type="number" id="zbrainRunAnnual" value="348453" min="0" step="10000" /><span class="post">/yr</span></div>
      </div>
      <div class="input-row">
        <label>
          Hypercare
          <span class="hint">Starts the week after engagement end</span>
        </label>
        <div class="field"><span class="pre">$</span><input type="number" id="zbrainMaintAnnual" value="500000" min="0" step="10000" /><span class="post">/yr</span></div>
      </div>
      <div class="input-row">
        <label>
          Engagement window
          <span class="hint">Weeks from kickoff. Cost streams scale with this.</span>
        </label>
        <div class="field"><input type="number" id="contractWeeks" value="22" min="9" max="104" step="1" /><span class="post">wks</span></div>
      </div>
    </div>
  </div>
<!-- Math: where the weekly savings number comes from -->
  <div class="math-card">
    <h2 id="mathTitle">Weekly savings · how the go-live and steady-state numbers are calculated</h2>
    <div id="mathBox"></div>
    <p style="font-size:11.5px;color:var(--muted);margin:10px 0 0;line-height:1.55">
      <b>Cash share 70%</b> = the portion of free resources the customer takes as cash savings.
      The remaining 30% is capacity for new work, not reclaimed as cash on day one. We use the
      conservative 70% throughout.
    </p>
  </div>

  <div class="footnote">
    ZBrain MVP live at week 8; efficiency ramps linearly go-live → steady-state over the
    live weeks of the engagement. Cost lines: implementation covers weeks 1 to engagement
    end; platform run cost starts at go-live; hypercare kicks in the week after engagement
    end. The SI side uses the SAME weekly rates for platform run and hypercare so both
    sides itemise identically; only time-in-market moves the comparison. Reimplementation
    risk is NOT included on the SI side; every week of slip widens the gap.
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
  return (neg ? "-" : "") + "$" + Math.round(v).toLocaleString();
}
function fmtPlus(v) {
  if (v > 0) return "+" + fmt(v);
  return fmt(v);
}

// Fixed engagement parameters (everything else is editable).
const ZBRAIN_BUILD_WEEKS = 8;       // ZBrain MVP go-live
const REDEPLOY_FACTOR = 0.70;       // share of gross savings that's cash
const HORIZON_WEEKS_LONG = 52;      // 12-month view from kickoff

// Ramp model: efficiency goes from goLiveEff at week BUILD+1 to steadyEff
// at week BUILD + rampLen, then holds at steadyEff. Linear ramp.
// rampLen defaults to the live duration in the contract window so the
// "at contract end" number already reflects partial-maturity. Past contract
// end, efficiency stays at steady-state.
function effAtLiveWeek(k, goLiveEff, steadyEff, rampLen) {
  // k is 1-indexed: k=1 is the first live week.
  if (k <= 0) return 0;
  if (rampLen <= 1) return steadyEff;
  if (k >= rampLen) return steadyEff;
  const t = (k - 1) / (rampLen - 1);
  return goLiveEff + (steadyEff - goLiveEff) * t;
}

function sumRecovered(liveWeeks, annualBaseline, goLiveEff, steadyEff, rampLen) {
  if (liveWeeks <= 0) return 0;
  let total = 0;
  for (let k = 1; k <= liveWeeks; k++) {
    const eff = effAtLiveWeek(k, goLiveEff, steadyEff, rampLen);
    total += (annualBaseline * eff * REDEPLOY_FACTOR) / 52;
  }
  return total;
}

function compute() {
  const ftes              = num("ftes");
  const cpf               = num("costPerFte");
  const steadyEff         = num("efficiency") / 100;
  const goLiveEff         = num("goLiveEff") / 100;
  const zbrainRunAnnual   = num("zbrainRunAnnual");
  const zbrainMaintAnnual = num("zbrainMaintAnnual");
  const zbrainImpl        = num("zbrainImpl");
  const contractWeeks     = Math.max(ZBRAIN_BUILD_WEEKS + 1, num("contractWeeks"));
  const compWeeks         = Math.max(ZBRAIN_BUILD_WEEKS, num("compWeeks"));
  const compInvest        = num("compInvest");

  const annualBaseline = ftes * cpf;
  const annualCash     = annualBaseline * steadyEff * REDEPLOY_FACTOR;
  const steadyWeekly   = annualCash / 52;

  // Ramp length: from go-live (week 9) to steady-state at contract end.
  // Matches the live window inside the engagement.
  const liveWeeksContract = Math.max(0, contractWeeks - ZBRAIN_BUILD_WEEKS);
  const rampLen = liveWeeksContract; // ramp completes exactly at contract end

  // Two ongoing cost streams with DIFFERENT start dates:
  //   - Platform run: starts at go-live (week 9). Real traffic = real model cost.
  //   - Support & governance: starts AFTER hypercare (week 23). L1/L2 + evals.
  const zbrainRunWeekly   = zbrainRunAnnual / 52;
  const zbrainMaintWeekly = zbrainMaintAnnual / 52;

  // HORIZON 1: SI go-live (week compWeeks) -------------------------------
  // This is the head-to-head moment. ZBrain has been live for
  // (compWeeks - 8) weeks; SI is JUST going live with 0 weeks of value.
  // Investment lines for ZBrain by then:
  //   - implementation: fully booked (covers weeks 1 → engagement end)
  //   - platform run: 1 week per live week post-go-live
  //   - hypercare: from (engagement end + 1) up to this horizon
  const horizonShort = compWeeks;
  const zbrainLiveH1   = Math.max(0, horizonShort - ZBRAIN_BUILD_WEEKS);
  const zbrainHyperWeeksH1 = Math.max(0, horizonShort - contractWeeks);
  const zbrainRecoveredH1  = sumRecovered(zbrainLiveH1, annualBaseline, goLiveEff, steadyEff, rampLen);
  const zbrainRunCostH1    = zbrainRunWeekly  * zbrainLiveH1;
  const zbrainHyperCostH1  = zbrainMaintWeekly * zbrainHyperWeeksH1;
  const zbrainTotalCostH1  = zbrainImpl + zbrainRunCostH1 + zbrainHyperCostH1;
  const zbrainNetH1        = zbrainRecoveredH1 - zbrainTotalCostH1;

  // SI at SI go-live: 0 live weeks, fixed-price implementation only.
  const compLiveH1         = 0;
  const compRecoveredH1    = 0;
  const compRunCostH1      = 0;
  const compHyperCostH1    = 0;
  const compTotalCostH1    = compInvest;
  const compNetH1          = -compTotalCostH1;

  // HORIZON 2: 12 months from kickoff (week 52) --------------------------
  // ZBrain has been live 44 weeks; SI has been live (52 - compWeeks) weeks.
  // Both sides itemise impl + platform run + hypercare with the SAME unit
  // rates; the gap turns on time-in-market, not cost-line tricks.
  const liveWeeks12mo        = HORIZON_WEEKS_LONG - ZBRAIN_BUILD_WEEKS;
  const maintWeeks12mo       = Math.max(0, HORIZON_WEEKS_LONG - contractWeeks);
  const zbrainRecovered12mo  = sumRecovered(liveWeeks12mo, annualBaseline, goLiveEff, steadyEff, rampLen);
  const zbrainRunCost12mo    = zbrainRunWeekly  * liveWeeks12mo;
  const zbrainHyperCost12mo  = zbrainMaintWeekly * maintWeeks12mo;
  const zbrainTotalCost12mo  = zbrainImpl + zbrainRunCost12mo + zbrainHyperCost12mo;
  const zbrainNet12mo        = zbrainRecovered12mo - zbrainTotalCost12mo;

  const compLiveWeeks12mo    = Math.max(0, HORIZON_WEEKS_LONG - compWeeks);
  const compRecovered12mo    = sumRecovered(compLiveWeeks12mo, annualBaseline, goLiveEff, steadyEff, rampLen);
  // SI ongoing platform run from SI go-live. Hypercare starts after SI's
  // own hypercare-equivalent window (mirror ZBrain's: live-weeks-of-engagement).
  const compRunCost12mo      = zbrainRunWeekly  * compLiveWeeks12mo;
  const compHyperLen         = liveWeeksContract; // same shape as ZBrain
  const compHyperWeeks12mo   = Math.max(0, HORIZON_WEEKS_LONG - (compWeeks + compHyperLen));
  const compHyperCost12mo    = zbrainMaintWeekly * compHyperWeeks12mo;
  const compTotalCost12mo    = compInvest + compRunCost12mo + compHyperCost12mo;
  const compNet12mo          = compRecovered12mo - compTotalCost12mo;

  // Head start math: ZBrain captures value during weeks (BUILD..compWeeks).
  const headstartWeeks = Math.max(0, compWeeks - ZBRAIN_BUILD_WEEKS);
  const headstartValue = sumRecovered(headstartWeeks, annualBaseline, goLiveEff, steadyEff, rampLen);

  return {
    ftes, cpf, steadyEff, goLiveEff,
    steadyWeekly, annualCash, annualBaseline,
    zbrainImpl, zbrainRunAnnual, zbrainMaintAnnual,
    contractWeeks, compWeeks, compInvest,
    liveWeeksContract, rampLen,
    // Horizon 1: SI go-live
    horizonShort,
    zbrainLiveH1, zbrainHyperWeeksH1, zbrainRecoveredH1, zbrainRunCostH1, zbrainHyperCostH1, zbrainTotalCostH1, zbrainNetH1,
    compLiveH1, compRecoveredH1, compRunCostH1, compHyperCostH1, compTotalCostH1, compNetH1,
    // Horizon 2: 12 months
    liveWeeks12mo, maintWeeks12mo,
    zbrainRecovered12mo, zbrainRunCost12mo, zbrainHyperCost12mo, zbrainTotalCost12mo, zbrainNet12mo,
    compLiveWeeks12mo, compHyperWeeks12mo, compRecovered12mo, compRunCost12mo, compHyperCost12mo, compTotalCost12mo, compNet12mo,
    headstartWeeks, headstartValue,
  };
}

function renderTimelines(c) {
  // Bar scales from week 1 to SI go-live (compWeeks). That is the head-to-head
  // moment the headline tiles + compare block are anchored on.
  const win = Math.max(c.horizonShort, ZBRAIN_BUILD_WEEKS + 1);
  const pctOfWin = function (weeks) {
    return Math.max(0, Math.min(100, (weeks / win) * 100));
  };

  // ZBrain bar: 8 wks build + (win - 8) wks live, with a subtle vertical
  // marker where the engagement ends and hypercare begins.
  const tlZ = $("tlZbrain");
  const buildPct = pctOfWin(ZBRAIN_BUILD_WEEKS);
  const livePct  = pctOfWin(c.zbrainLiveH1);
  const engEndPct = pctOfWin(c.contractWeeks);
  const showMarker = c.contractWeeks > ZBRAIN_BUILD_WEEKS && c.contractWeeks < win;
  tlZ.innerHTML =
    '<div class="tl-build" style="width:' + buildPct + '%">build · 8 wks</div>'
    + '<div class="tl-live"  style="left:'  + buildPct + '%; width:' + livePct + '%">live · ' + c.zbrainLiveH1 + ' wks</div>'
    + (showMarker
        ? '<div class="tl-marker" style="left:' + engEndPct + '%" title="engagement end · hypercare starts"></div>'
          + '<div class="tl-marker-lbl" style="left:' + engEndPct + '%">eng. end (wk ' + c.contractWeeks + ')</div>'
        : '');
  $("tlZbrainSub").textContent = "8 wks build, " + c.zbrainLiveH1 + " wks live";

  // SI bar: all build, the full width of the window.
  const tlC = $("tlComp");
  if (c.compWeeks <= win) {
    const siBuildPct = pctOfWin(c.compWeeks);
    const siLivePct  = pctOfWin(c.compLiveH1);
    tlC.innerHTML =
      '<div class="tl-build" style="width:' + siBuildPct + '%">build · ' + c.compWeeks + ' wks</div>'
      + '<div class="tl-live"  style="left:'  + siBuildPct + '%; width:' + siLivePct + '%">live · ' + c.compLiveH1 + ' wks</div>';
  } else {
    tlC.innerHTML =
      '<div class="tl-pending" style="width:100%">still building at week ' + win + ' (target wk ' + c.compWeeks + ')</div>';
  }
  $("tlCompSub").textContent = c.compWeeks + " wks build, " + c.compLiveH1 + " wks live";

  $("tlEndTick").textContent = "Week " + win + " · SI go-live";
  $("tlTitle").textContent = "Build vs live timeline";
}

function renderTakeaway(c) {
  const deltaH1 = c.zbrainNetH1 - c.compNetH1;
  const t = $("takeaway");
  if (c.compWeeks <= ZBRAIN_BUILD_WEEKS) {
    t.innerHTML = "Both paths deliver inside the same window. Open the full benefit-case calculator for the multi-year view.";
    return;
  }
  t.innerHTML =
    "ZBrain captures <b>" + fmt(c.zbrainRecoveredH1) + "</b> of FTE savings during the <b>" +
    c.headstartWeeks + " weeks</b> the SI is still in build. " +
    "At SI go-live (week " + c.horizonShort + "), ZBrain is <b>" + fmt(Math.abs(deltaH1)) + "</b> ahead, " +
    "and the gap widens every week the SI ramp lags.";
}

function renderMath(c) {
  const m = $("mathBox");
  if (!m) return;
  const grossSteady  = c.annualBaseline * c.steadyEff;
  const cashSteady   = grossSteady * REDEPLOY_FACTOR;
  const weeklySteady = cashSteady / 52;
  const ftesSteady   = c.ftes * c.steadyEff * REDEPLOY_FACTOR;
  const grossGo      = c.annualBaseline * c.goLiveEff;
  const cashGo       = grossGo * REDEPLOY_FACTOR;
  const weeklyGo     = cashGo / 52;
  // Dynamic title so the example dollar amounts stay in sync with the inputs.
  const t = $("mathTitle");
  if (t) {
    const goK     = Math.round(weeklyGo / 1000);
    const steadyK = Math.round(weeklySteady / 1000);
    t.textContent = "Weekly savings · how the $" + goK + "K and $" + steadyK + "K are calculated";
  }
  const ftesGo       = c.ftes * c.goLiveEff * REDEPLOY_FACTOR;
  m.innerHTML =
    '<div class="math-line"><span>Baseline annual CSR cost</span>'
      + '<span class="math-eq">' + c.ftes.toLocaleString() + ' FTE × $' + c.cpf.toLocaleString() + ' = <b>' + fmtFull(c.annualBaseline) + '</b> / yr</span></div>'
    + '<div class="math-section">Steady-state weekly savings (week ' + c.contractWeeks + ' onward, ' + Math.round(c.steadyEff*100) + '% efficiency)</div>'
    + '<div class="math-line"><span>Gross savings</span>'
      + '<span class="math-eq">' + fmt(c.annualBaseline) + ' × ' + Math.round(c.steadyEff*100) + '% = <b>' + fmtFull(grossSteady) + '</b> / yr</span></div>'
    + '<div class="math-line"><span>Cash savings (70% as cash)</span>'
      + '<span class="math-eq">' + fmt(grossSteady) + ' × 70% = <b>' + fmtFull(cashSteady) + '</b> / yr</span></div>'
    + '<div class="math-line emph"><span>Steady-state weekly</span>'
      + '<span class="math-eq">' + fmt(cashSteady) + ' ÷ 52 = <b>' + fmtFull(weeklySteady) + '</b> / wk</span></div>'
    + '<div class="math-line"><span>Free resources at steady state</span>'
      + '<span class="math-eq">' + c.ftes.toLocaleString() + ' × ' + Math.round(c.steadyEff*100) + '% × 70% = <b>' + Math.round(ftesSteady).toLocaleString() + ' FTE</b></span></div>'
    + '<div class="math-section">Go-live weekly savings (week 9, ' + Math.round(c.goLiveEff*100) + '% efficiency)</div>'
    + '<div class="math-line"><span>Gross savings</span>'
      + '<span class="math-eq">' + fmt(c.annualBaseline) + ' × ' + Math.round(c.goLiveEff*100) + '% = <b>' + fmtFull(grossGo) + '</b> / yr</span></div>'
    + '<div class="math-line"><span>Cash savings (70% as cash)</span>'
      + '<span class="math-eq">' + fmt(grossGo) + ' × 70% = <b>' + fmtFull(cashGo) + '</b> / yr</span></div>'
    + '<div class="math-line emph"><span>Go-live weekly</span>'
      + '<span class="math-eq">' + fmt(cashGo) + ' ÷ 52 = <b>' + fmtFull(weeklyGo) + '</b> / wk</span></div>'
    + '<div class="math-line"><span>Free resources at go-live</span>'
      + '<span class="math-eq">' + c.ftes.toLocaleString() + ' × ' + Math.round(c.goLiveEff*100) + '% × 70% = <b>' + Math.round(ftesGo).toLocaleString() + ' FTE</b></span></div>'
    + (function () {
        // Two-line shortcut to explain the head-start total on a call without
        // teaching anyone the linear-ramp model. Splits the engagement-live
        // weeks in half: first half at go-live efficiency, second half (plus
        // any post-engagement weeks before SI go-live) at steady state.
        const liveTotal      = c.horizonShort - 8;
        const engagementLive = c.contractWeeks - 8;
        const earlyWeeks     = Math.floor(engagementLive / 2);
        const lateWeeks      = Math.max(0, liveTotal - earlyWeeks);
        const earlyVal       = earlyWeeks * weeklyGo;
        const lateVal        = lateWeeks  * weeklySteady;
        const simpleTotal    = earlyVal + lateVal;
        const goPct          = Math.round(c.goLiveEff * 100);
        const stPct          = Math.round(c.steadyEff * 100);
        return (
          '<div class="math-foot">'
          + 'Quick way to read the head-start total: first <b>' + earlyWeeks + '</b> live weeks at '
            + goPct + '% efficiency (' + fmtFull(weeklyGo) + '/wk) plus next <b>' + lateWeeks
            + '</b> weeks at ' + stPct + '% efficiency (' + fmtFull(weeklySteady) + '/wk)'
            + ' = ' + fmtFull(earlyVal) + ' + ' + fmtFull(lateVal) + ' = <b>' + fmtFull(simpleTotal) + '</b>.<br>'
          + 'The page uses a continuous linear ramp underneath; this two-stage shortcut lands at the same total.'
          + '</div>'
        );
      })();
}

function render() {
  const c = compute();
  $("hlVsCompetitor").textContent   = "vs SI alternative: " + c.compWeeks + " weeks";
  $("hlSavingsRate").textContent    = fmt(c.steadyWeekly) + " / wk";
  const weeklyGo = (c.annualBaseline * c.goLiveEff * REDEPLOY_FACTOR) / 52;
  $("hlGoLiveRate").textContent     = "go-live rate: " + fmt(weeklyGo) + " / wk";
  const ftesSteady = c.ftes * c.steadyEff * REDEPLOY_FACTOR;
  const ftesGo     = c.ftes * c.goLiveEff * REDEPLOY_FACTOR;
  $("hlFtesRedeployed").textContent =
    Math.round(ftesSteady) + " free resources (steady) · " + Math.round(ftesGo) + " at go-live";
  const endLabel = "Recovered at SI go-live (week " + c.horizonShort + ")";
  $("hlZbrainRecoveredLbl").textContent = endLabel + " · ZBrain";
  $("hlZbrainRecovered").textContent    = fmt(c.zbrainRecoveredH1);
  $("hlZbrainLiveWeeks").textContent    = c.zbrainLiveH1 + " live weeks, ramping " +
    Math.round(c.goLiveEff*100) + "% → " + Math.round(c.steadyEff*100) + "%";

  const advH1 = c.zbrainNetH1 - c.compNetH1;
  $("hlAdvantageLbl").textContent  = "ZBrain advantage at week " + c.horizonShort;
  $("hlAdvantage").textContent     = fmtPlus(advH1);
  $("hlAdvantageSub").textContent  = "ZBrain net " + fmt(c.zbrainNetH1) + " vs SI net " + fmt(c.compNetH1);

  // Horizon 1: at SI go-live
  const h1Hdr = "At SI go-live (week " + c.horizonShort + ")";
  $("vsZbrainEndLbl").textContent        = h1Hdr;
  $("vsCompEndLbl").textContent          = h1Hdr;
  $("vsZbrainLiveDec").textContent       = c.zbrainLiveH1 + " weeks";
  $("vsZbrainImplH1").textContent        = fmt(c.zbrainImpl);
  $("vsZbrainRunH1").textContent         = fmt(c.zbrainRunCostH1) + "  (" + c.zbrainLiveH1 + " wks)";
  $("vsZbrainHyperH1").textContent       = fmt(c.zbrainHyperCostH1) + "  (" + c.zbrainHyperWeeksH1 + " wks)";
  $("vsZbrainCostDec").textContent       = fmt(c.zbrainTotalCostH1);
  $("vsZbrainRecoveredDec").textContent  = fmt(c.zbrainRecoveredH1);
  $("vsZbrainNetDec").textContent        = fmtPlus(c.zbrainNetH1);
  $("vsCompLiveDec").textContent         = c.compLiveH1 + " weeks";
  $("vsCompRunH1").textContent           = fmt(c.compRunCostH1)   + "  (0 wks)";
  $("vsCompHyperH1").textContent         = fmt(c.compHyperCostH1) + "  (0 wks)";
  $("vsCompTotalH1").textContent         = fmt(c.compTotalCostH1);
  $("vsCompRecoveredDec").textContent    = fmt(c.compRecoveredH1);
  $("vsCompNetDec").textContent          = fmtPlus(c.compNetH1);

  $("tlZbrainSavings").textContent = fmt(c.zbrainRecoveredH1);
  $("tlCompSavings").textContent   = fmt(c.compRecoveredH1);

  renderMath(c);
  renderTimelines(c);
  renderTakeaway(c);
}

document.addEventListener("input", function (ev) {
  if (ev.target && ev.target.tagName === "INPUT") render();
});
render();
</script>
</body>
</html>
"""

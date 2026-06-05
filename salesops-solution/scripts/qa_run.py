"""End-to-end QA harness — runs the pipeline against a representative sample
of seeded emails and prints a summary table."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    (1, "Clean PO + cal cert (Bluehawk, en)", ["po_intake", "L4_AUTO"]),
    (5, "Clean PO Vertex (research, en)", ["po_intake", "L4_AUTO"]),
    (3, "Clean PO Nordstern (es)", ["po_intake", "L4_AUTO"]),
    (4, "Clean PO Ozeki (ja)", ["po_intake", "L4_AUTO"]),
    (6, "JA scanned PO image (OCR)", ["po_intake"]),
    (7, "Q2O w/ price mismatch (Raytheon)", ["quote_to_order"]),
    (8, "Q2O w/ qty mismatch (TSMC)", ["quote_to_order"]),
    (9, "Q2O w/ extra SKU (Meridian, es)", ["quote_to_order"]),
    (10, "Clean Q2O + PDF+XLSX+DOCX (Aurora)", ["quote_to_order"]),
    (11, "Hold release — credit cleared (Bluehawk)", ["hold_release"]),
    (14, "Export-compliance hold release (Raytheon)", []),
    (16, "Delivery reschedule (TSMC)", ["delivery_change"]),
    (19, "Cal request ISO 17025 (Finolab)", ["service_order"]),
    (20, "Cal request Z540.3 MIL-STD (Raytheon)", ["service_order"]),
    (22, "JA repair request UXR Ch3 trig", ["service_order"]),
    (23, "URGENT WO status (TSMC)", ["wo_status_inquiry"]),
    (26, "EOL roadmap question", ["general_inquiry"]),
    (28, "Phishing wire-fraud", ["spam"]),
    (29, "Promo spam", ["spam"]),
    (30, "Ambiguous 'status?'", []),
    (31, "Forwarded thread", []),
]


def post(path):
    req = urllib.request.Request(BASE + path, method="POST", data=b"")
    return json.loads(urllib.request.urlopen(req).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


def wait_pipeline(pid, deadline=240):
    t0 = time.time()
    while time.time() - t0 < deadline:
        d = get(f"/api/pipelines/{pid}")
        if d["status"] in ("completed", "error", "discarded", "awaiting_hitl", "rejected"):
            return d
        time.sleep(2)
    return get(f"/api/pipelines/{pid}")


print(f"running {len(SCENARIOS)} scenarios sequentially…")
print()
print(f"{'id':>3}  {'scenario':<48}  {'intent':<22}  {'lang':<3}  {'tier':<14}  {'conf':>5}  {'status':<14}  {'mismatch':<22}  {'reply?':<7}")
print("-" * 170)
results = []
for eid, label, expects in SCENARIOS:
    started = time.time()
    res = post(f"/api/pipelines/run/{eid}")
    pipe = wait_pipeline(res["pipeline_id"])
    dt = time.time() - started
    intent = pipe.get("intent") or "—"
    lang = pipe.get("language") or "—"
    tier = pipe.get("autonomy_tier") or "—"
    conf = pipe.get("confidence")
    conf_s = f"{conf:.2f}" if conf is not None else "—"
    status = pipe.get("status")
    recon = pipe.get("reconcile") or {}
    mismatch_summary = ""
    if recon.get("issues"):
        kinds = sorted({i["kind"] for i in recon["issues"]})
        mismatch_summary = ",".join(kinds)[:22]
    elif recon.get("checked"):
        mismatch_summary = "✓ clean"
    reply = "yes" if (pipe.get("reply") or {}).get("body") else "no"
    print(
        f"{eid:>3}  {label:<48}  {intent:<22}  {lang:<3}  {tier:<14}  {conf_s:>5}  {status:<14}  {mismatch_summary:<22}  {reply:<7}  ({dt:.0f}s)"
    )
    results.append((eid, label, intent, lang, tier, conf, status, mismatch_summary, expects))

print()
print("=== checks ===")
fails = []
for eid, label, intent, lang, tier, conf, status, mm, expects in results:
    for exp in expects:
        if exp.startswith("L"):
            if tier != exp:
                fails.append(f"  id={eid} {label}: expected tier {exp}, got {tier}")
        else:
            if intent != exp:
                fails.append(f"  id={eid} {label}: expected intent {exp}, got {intent}")
if fails:
    print(f"FAIL: {len(fails)} mismatches against expectations")
    for f in fails:
        print(f)
else:
    print("PASS: all hard expectations met.")

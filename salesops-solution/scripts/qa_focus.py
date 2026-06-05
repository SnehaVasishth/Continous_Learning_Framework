"""Focused QA — re-runs only the cases relevant to the reconcile fix
plus the must-be-HITL ambiguity case, to verify routing across all 3 tiers."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    (1, "Clean PO + cal cert (Bluehawk, en)", ["po_intake", "L4_AUTO"]),
    (3, "Clean PO Nordstern (es)", ["po_intake", "L4_AUTO"]),
    (4, "Clean PO Ozeki (ja)", ["po_intake", "L4_AUTO"]),
    (5, "Clean PO Vertex (research, en)", ["po_intake", "L4_AUTO"]),
    (6, "JA scanned PO image (OCR)", ["po_intake"]),
    (7, "Q2O w/ price mismatch (Raytheon)", ["quote_to_order"]),
    (8, "Q2O w/ qty mismatch (TSMC)", ["quote_to_order"]),
    (9, "Q2O w/ extra SKU (Meridian, es)", ["quote_to_order"]),
    (10, "Clean Q2O + PDF+XLSX+DOCX (Aurora)", ["quote_to_order"]),
    (30, "Ambiguous 'status?'", []),
]


def post(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + path, method="POST", data=b"")).read())


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


print(f"{'id':>3}  {'scenario':<48}  {'intent':<22}  {'lang':<3}  {'tier':<14}  {'conf':>5}  {'status':<14}  {'reconcile':<28}")
print("-" * 160)
for eid, label, expects in SCENARIOS:
    res = post(f"/api/pipelines/run/{eid}")
    pipe = wait_pipeline(res["pipeline_id"])
    intent = pipe.get("intent") or "—"
    lang = pipe.get("language") or "—"
    tier = pipe.get("autonomy_tier") or "—"
    conf = pipe.get("confidence")
    conf_s = f"{conf:.2f}" if conf is not None else "—"
    status = pipe.get("status")
    recon = pipe.get("reconcile") or {}
    if not recon.get("checked"):
        recon_s = "skipped"
    elif recon.get("issues"):
        recon_s = "issues: " + ",".join(sorted({i["kind"] for i in recon["issues"]}))[:18]
    elif recon.get("matched_quote"):
        recon_s = f"clean ({recon['matched_quote']['quote_number'][:12]})"
    else:
        recon_s = recon.get("notes", ["—"])[0][:26]
    print(f"{eid:>3}  {label:<48}  {intent:<22}  {lang:<3}  {tier:<14}  {conf_s:>5}  {status:<14}  {recon_s:<28}")

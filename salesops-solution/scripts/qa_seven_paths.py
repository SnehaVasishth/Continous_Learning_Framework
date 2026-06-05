"""Run one representative scenario per RFP happy path and print a clean ASCII table."""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

# Each tuple: (email_id, label, expected intent, expected RFP track)
SEVEN_PATHS = [
    (1, "Trade Order Entry: clean PO (Bluehawk en)", "po_intake", "trade_order_entry"),
    (10, "Trade Order Entry: Q2O conversion (Aurora multi-attach)", "quote_to_order", "trade_order_entry"),
    (32, "Trade Sales Change Order: qty bump + add (Raytheon)", "trade_change_order", "trade_change_order"),
    (34, "SSD Change: pull-in (TSMC NPI gating)", "ssd_change_request", "ssd_change"),
    (41, "SOM Create: multi-asset cal (TSMC)", "service_order", "som_create"),
    (37, "SOM Update: add assets to open WO", "wo_update_request", "som_update"),
    (24, "SOM Inquiry: WO status (TSMC)", "wo_status_inquiry", "som_inquiry"),
    (38, "Service Contracts: 3-yr Cal Plan quote", "service_contract_request", "service_contract"),
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


print(f"{'id':>3}  {'scenario':<55}  {'intent':<25}  {'expected':<25}  {'tier':<14}  {'conf':>5}  {'status':<14}  match")
print("-" * 175)

passes = 0
fails = []
for eid, label, exp_intent, exp_track in SEVEN_PATHS:
    res = post(f"/api/pipelines/run/{eid}")
    pipe = wait_pipeline(res["pipeline_id"])
    intent = pipe.get("intent") or "-"
    tier = pipe.get("autonomy_tier") or "-"
    conf = pipe.get("confidence")
    conf_s = f"{conf:.2f}" if conf is not None else "-"
    status = pipe.get("status")
    ok = intent == exp_intent
    if ok:
        passes += 1
    else:
        fails.append((eid, label, intent, exp_intent))
    mark = "PASS" if ok else "FAIL"
    print(
        f"{eid:>3}  {label:<55}  {intent:<25}  {exp_intent:<25}  {tier:<14}  {conf_s:>5}  {status:<14}  {mark}"
    )

print("-" * 175)
print(f"summary: {passes}/{len(SEVEN_PATHS)} intent classifications correct")
if fails:
    print("misclassified:")
    for eid, label, got, exp in fails:
        print(f"  id={eid} {label}: expected {exp}, got {got}")
    sys.exit(1)

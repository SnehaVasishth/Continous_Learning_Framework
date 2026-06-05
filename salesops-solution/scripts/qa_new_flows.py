"""Verify the new RFP flow paths route correctly: trade change order, SSD
change, WO update, service contract, multi-asset SOM, misroute."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    (32, "Trade change order — qty + add line + bill-to (Raytheon)", "trade_change_order"),
    (33, "Trade change order #2 (Aurora)", "trade_change_order"),
    (34, "SSD change — pull-in (TSMC)", "ssd_change_request"),
    (35, "SSD change — partial split (Aurora)", "ssd_change_request"),
    (36, "WO update — add note + task (es Meridian)", "wo_update_request"),
    (37, "WO update — add 2 assets (Finolab)", "wo_update_request"),
    (38, "Service contract quote — Cal Plan 3y (Bluehawk)", "service_contract_request"),
    (39, "Service contract renewal (Raytheon)", "service_contract_request"),
    (40, "Service contract PM plan (es Nordstern)", "service_contract_request"),
    (41, "Multi-asset cal request — 6 instruments (TSMC)", "service_order"),
    (42, "Misrouted: WO + invoice mixed (Vertex)", None),
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


print(f"{'id':>3}  {'scenario':<55}  {'intent':<25}  {'lang':<3}  {'tier':<14}  {'conf':>5}  {'status':<14}  {'expect':<25}")
print("-" * 175)
fails = 0
for eid, label, expected in SCENARIOS:
    res = post(f"/api/pipelines/run/{eid}")
    pipe = wait_pipeline(res["pipeline_id"])
    intent = pipe.get("intent") or "—"
    lang = pipe.get("language") or "—"
    tier = pipe.get("autonomy_tier") or "—"
    conf = pipe.get("confidence")
    conf_s = f"{conf:.2f}" if conf is not None else "—"
    status = pipe.get("status")
    matched = "✓" if (expected is None or intent == expected) else "✗"
    if expected is not None and intent != expected:
        fails += 1
    exp_str = expected or "(any)"
    print(f"{eid:>3}  {label:<55}  {intent:<25}  {lang:<3}  {tier:<14}  {conf_s:>5}  {status:<14}  {exp_str:<25} {matched}")

print()
if fails == 0:
    print("PASS: all new flow paths classified correctly.")
else:
    print(f"FAIL: {fails} intent misclassifications.")

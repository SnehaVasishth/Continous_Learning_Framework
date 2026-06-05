"""Long email-thread scenarios (10 to 40 messages each).

Adds depth to the seed corpus by simulating real-world multi-week customer
conversations: PO clarifications, work-order escalations, shipping issues,
export-compliance reviews, EOL migrations, multi-asset fan-outs.

Registered into seed_threads.SCENARIOS via the EXTRA_SCENARIOS list at the
bottom of this module. Run with `python -m app.scripts.seed_threads` to
seed all scenarios (base + extra).
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Scenario 1 — Ozeki Test Systems · long PO clarification · 22 messages · EN
# ---------------------------------------------------------------------------

OZEKI_PO_LONG_EN: dict[str, Any] = {
    "key": "ozeki_po_long_en",
    "customer_code": "OZEKI-T&M-088",
    "language": "en",
    "subject_root": "PO-OZEKI-2026-0418 — quantity revisions, lead time, and split shipment to Tokyo + Osaka",
    "intent_hint": "po_intake",
    "messages": [
        {"from": "buyer", "delay_min": 0, "body": (
            "Hi ZBrain Sales Ops team,\n\n"
            "Please find attached our purchase order PO-OZEKI-2026-0418 against quote QT-OZEKI-T&M-088-DEMO. "
            "We are placing an order for the following items:\n\n"
            "  Line 1 — 4x N5247B-419 PNA-X Microwave Network Analyzers, 67 GHz, 4-port\n"
            "  Line 2 — 4x 85052D 3.5 mm Economy Calibration Kits\n"
            "  Line 3 — 4x CAL-Z540-1Y annual calibration service with as-found data\n\n"
            "Couple of operational requests:\n"
            "  - Net 30 payment terms per our master agreement, please confirm\n"
            "  - Ship two units (line 1 + accessories) to our Tokyo lab and the remaining two to the Osaka lab\n"
            "  - Need ECCN classifications on all line items for our import-export filing\n"
            "  - Expedite line 1 if at all possible; our Q3 acceptance milestone falls on July 15\n\n"
            "Thanks,\nKenji Watanabe\nPurchasing Manager — Ozeki Test Systems\n+81 3 5555 0188"
        ), "attachments": [{"kind": "po", "po_number": "PO-OZEKI-2026-0418",
            "line_items": [
                {"sku": "N5247B-419", "description": "PNA-X Microwave Network Analyzer, 67 GHz, 4-port", "qty": 4, "unit_price": 218500},
                {"sku": "85052D", "description": "3.5 mm Economy Calibration Kit, DC to 26.5 GHz", "qty": 4, "unit_price": 4750},
                {"sku": "CAL-Z540-1Y", "description": "Calibration Service - Z540.3 compliant, 1-year", "qty": 4, "unit_price": 1850},
            ]}]},
        {"from": "csr", "delay_min": 22, "body": (
            "Hi Kenji,\n\n"
            "PO received and confirmed. Walking through the validation now. Quick first-pass answers:\n\n"
            "  - Net 30 terms confirmed against your master account, no changes\n"
            "  - Split shipment to Tokyo and Osaka noted, I will get the ship-to addresses confirmed in the next email\n"
            "  - ECCN classifications: N5247B-419 is 3A002.f, 85052D is EAR99, CAL-Z540-1Y is service (not subject to ECCN)\n"
            "  - Line 1 expedite: current lead time is 16 weeks ex-works; let me check expedite slots with the factory and revert\n\n"
            "I will have full SOA in your inbox within 24 hours, expedite confirmation by end of week.\n\n"
            "Best,\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 240, "body": (
            "Thanks for the quick turnaround. Quick correction — please use the following ship-to addresses:\n\n"
            "  Tokyo lab (2 units):\n"
            "    Ozeki Test Systems\n"
            "    Attn: Receiving — Calibration Lab\n"
            "    東京都品川区西五反田 7-22-17\n"
            "    Tokyo 141-0031, Japan\n\n"
            "  Osaka lab (2 units):\n"
            "    Ozeki Test Systems Osaka Office\n"
            "    Attn: Mr. Takeshi Yamamoto\n"
            "    大阪市北区中之島 6-2-27\n"
            "    Osaka 530-0005, Japan\n\n"
            "Also — can we get the calibration certificates issued in both English and Japanese? Our customer audit "
            "in October requires bilingual documentation.\n\n"
            "Kenji"), "attachments": []},
        {"from": "csr", "delay_min": 18, "body": (
            "Got it, both ship-to addresses confirmed and added to the order record. Bilingual calibration certificates "
            "are standard for our Japan-market deliveries, so EN + JA cal certs will ship with each unit at no additional cost.\n\n"
            "ZBrain Sales Ops Desk"), "attachments": []},
        {"from": "csr", "delay_min": 1305, "body": (
            "Hi Kenji,\n\n"
            "Update on the expedite check. The factory has two slots that could pull line 1 in by approximately 4 weeks — "
            "they are willing to do a partial-week-by-week build for the first two units, which gets you a 12-week lead time "
            "on the Tokyo pair. Osaka pair stays at 16 weeks. Cost impact is a 6% expedite fee on the first two units only.\n\n"
            "Net cost: $26,220 in expedite fees for the Tokyo pair, no change to Osaka. Worth it for the Q3 milestone?\n\n"
            "Let me know and I will lock the slots."), "attachments": []},
        {"from": "buyer", "delay_min": 167, "body": (
            "Yes, please proceed with the expedite on the Tokyo pair. Funding for the expedite fee is approved as a "
            "change order against PO line 1 — please add a Line 1A entry for $26,220 to keep our internal cost-allocation "
            "clean.\n\nKenji"), "attachments": []},
        {"from": "csr", "delay_min": 14, "body": (
            "Perfect. Change order CO-OZEKI-2026-0418-001 generated for the $26,220 expedite fee on PO line 1A. "
            "Updated SOA is on its way; sending the production build slots to the factory now to lock.\n\n"
            "ZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 3120, "body": (
            "Quick question — for the CAL-Z540-1Y service entries on the units going to Osaka, we may need a different "
            "calibration laboratory to perform the service. Our Osaka site has a pre-existing arrangement with a JCSS-accredited "
            "lab for traceability reasons. Is the warranty affected if we use that lab instead of yours?"), "attachments": []},
        {"from": "csr", "delay_min": 35, "body": (
            "Good question. Using a JCSS-accredited lab for the annual calibration on the Osaka units is fully compatible "
            "with the unit warranty as long as the calibration is performed within the recommended 12-month interval and "
            "documented per ISO/IEC 17025 traceability requirements. We can swap the Osaka CAL-Z540-1Y service entries to "
            "credit-only against your account, and you can apply the credit to either future service work or accessory purchases.\n\n"
            "Want me to issue the credit memo for the Osaka calibrations?"), "attachments": []},
        {"from": "buyer", "delay_min": 88, "body": (
            "Yes please — credit memo against the account is cleanest. We will retain the Tokyo calibrations as bookings since "
            "the Tokyo lab uses your service directly.\n\nKenji"), "attachments": []},
        {"from": "csr", "delay_min": 19, "body": (
            "Credit memo CM-OZEKI-2026-0418-002 issued for 2x CAL-Z540-1Y = $3,700 USD. Credit is now visible on your "
            "account ledger and stays valid for 24 months from issue.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 4452, "body": (
            "Hi team — checking in on the Tokyo expedite. Factory still on track for the 12-week ETA? Our test team is "
            "starting to plan the lab acceptance schedule.\n\nKenji"), "attachments": []},
        {"from": "csr", "delay_min": 41, "body": (
            "Tokyo expedite is on track. Factory just released the production work order this morning — first unit ships "
            "in 5 weeks, second unit ships in 7 weeks. Both arrive within the 12-week window. I will send tracking numbers as "
            "the units enter logistics.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 6201, "body": (
            "Got the tracking info on unit 1 — landed at Narita customs yesterday and cleared today. Expected delivery to "
            "the Tokyo lab is tomorrow morning per the Yamato manifest. Any pre-installation requirements we should be "
            "aware of? Power, environmental, calibration warm-up?"), "attachments": []},
        {"from": "csr", "delay_min": 28, "body": (
            "Pre-installation checklist for the N5247B-419:\n\n"
            "  - Power: 100-240 VAC single phase, ~25 A max inrush; recommend dedicated 30 A circuit\n"
            "  - Environment: 23 +/- 5 C; humidity 30-70% non-condensing; allow 1 hour warm-up before calibration\n"
            "  - Rack space: 4U 19-inch standard, or benchtop with 100mm rear clearance for ventilation\n"
            "  - Test cables: precision 1.85 mm or 3.5 mm cables for the 67 GHz front panel; use torque wrench for connector mating\n\n"
            "Bilingual cal cert will be in the shipping crate; original signed by the factory metrology lead. "
            "Let me know if you want me to schedule a remote installation walk-through with one of our applications engineers.\n\n"
            "ZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 1140, "body": (
            "Remote walk-through would be helpful, yes. Can we schedule for next Tuesday 14:00 JST? Our team lead Misaki "
            "Sato will be on the call, plus two test engineers."), "attachments": []},
        {"from": "csr", "delay_min": 22, "body": (
            "Tuesday 14:00 JST works. Calendar invite incoming from our applications team — Hiroshi Tanaka (Signal Integrity, "
            "based in Yokohama office) will lead the session. He will cover: power-up sequence, frequency-converter alignment, "
            "S-parameter calibration walk-through, and field-service hand-off. Plan for 90 minutes including Q&A.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 5040, "body": (
            "Installation walk-through went well, thanks. Unit is up and running, calibration verified against the included "
            "kit. One follow-up — we noticed the bilingual cal cert has a minor typo in our company name on the JA side "
            "(西吾田 vs 西五反田 — wrong kanji). Can we get a corrected certificate reissued? The EN side is fine.\n\nKenji"), "attachments": []},
        {"from": "csr", "delay_min": 16, "body": (
            "Apologies for the typo — the JA side will be reissued today. Original kanji is 西五反田 (Nishi-Gotanda), correct. "
            "I will route the corrected certificate to our metrology lab for re-signing and send it to your Tokyo lab "
            "address within 3 business days. No charge.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 11220, "body": (
            "Hi team — final update from us on this PO. Both Tokyo units are operational and entered our Q3 acceptance test "
            "this week. Osaka units arrived on schedule and our local team has powered them up. The bilingual cal cert reissue "
            "arrived clean. Closing this thread on our side; thank you for the support across the expedite, the credit memo, "
            "the bilingual certs, and the remote walk-through. We will reach out separately for the FY27 budget conversation.\n\n"
            "Best,\nKenji"), "attachments": []},
        {"from": "csr", "delay_min": 31, "body": (
            "Thanks Kenji, glad the PO landed cleanly. Logging this thread as closed on our side as well. CCC request "
            "CCC-OZEKI-T&M-088-0418 marked complete. Looking forward to the FY27 budget conversation — feel free to copy "
            "Naoko Iwasaki (your account manager) when that kicks off.\n\nBest regards,\nZBrain Sales Ops Desk"), "attachments": []},
    ],
}


# ---------------------------------------------------------------------------
# Scenario 2 — Vertex Quantum · cal escalation · 28 messages · EN
# ---------------------------------------------------------------------------

VERTEX_CAL_ESCALATION_EN: dict[str, Any] = {
    "key": "vertex_cal_escalation_en",
    "customer_code": "VERTEX-Q-053",
    "language": "en",
    "subject_root": "Cal Cert CC-VERTEX-2026-0211 — drift outside spec on PNA-X, request emergency recalibration",
    "intent_hint": "service_order",
    "messages": [
        {"from": "buyer", "delay_min": 0, "body": (
            "Hi ZBrain Sales Ops,\n\n"
            "We have an issue with our PNA-X (N5247B-419, serial SN-848312-KS) — verification measurement this morning "
            "shows the 2.4mm reference path is drifting +0.18 dB across 18 to 26 GHz, which is significantly outside the "
            "as-left calibration limits on cert CC-VERTEX-2026-0211. This unit is critical-path for our qubit characterization "
            "run next week.\n\n"
            "Three asks:\n"
            "  1. Confirm whether the drift is consistent with anything observed in the original calibration data\n"
            "  2. Schedule an emergency on-site recalibration as soon as physically possible\n"
            "  3. Send a remote diagnostic checklist we can run before the engineer arrives\n\n"
            "Priya Iyer\nLab PI — Qubit Control\nVertex Quantum Research"), "attachments": []},
        {"from": "csr", "delay_min": 18, "body": (
            "Hi Priya,\n\n"
            "Acknowledged, escalating to the field service team now. Pulling the original cal data from cert "
            "CC-VERTEX-2026-0211 — will have an answer on whether the drift is consistent with the original measurement "
            "within 2 hours. I am also paging our applications engineer for the diagnostic checklist.\n\n"
            "Cycle time on an emergency on-site at Boulder is typically 48 to 72 hours from confirmation. I will get you a "
            "firm slot in the next message.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "csr", "delay_min": 95, "body": (
            "Original cal data review:\n\n"
            "  - Calibration date: 2026-02-11\n"
            "  - As-found at 18-26 GHz path: within +/-0.08 dB of spec\n"
            "  - As-left at 18-26 GHz path: within +/-0.04 dB of spec\n"
            "  - Test cable serial used during calibration: TC-2348\n\n"
            "Your +0.18 dB drift is materially outside both the as-left bound and the manufacturer's stated 12-month "
            "drift envelope. Two possibilities: (a) reference path cable degradation, (b) connector wear on the front panel. "
            "Recommend running the diagnostic checklist (sending now) before the engineer rolls.\n\n"
            "Emergency on-site slot confirmed: 2026-05-15 (Friday), engineer arriving Boulder lab 08:30 local. WO number: "
            "WO-VERTEX-Q-053-EMERG-2026-0515. Engineer is Doug Park.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 12, "body": (
            "Thanks for the fast turnaround. Friday 08:30 works. Please send the diagnostic checklist — we have a few "
            "spare connectors and a torque wrench, can run it tomorrow."), "attachments": []},
        {"from": "csr", "delay_min": 22, "body": (
            "Diagnostic checklist:\n\n"
            "  1. Visual inspection of front-panel 2.4 mm connectors — look for thread damage, pin recession, debris\n"
            "  2. Torque-wrench check on all 2.4 mm connections — should be 8 in-lbs (0.9 N-m) for 2.4 mm\n"
            "  3. Substitute the user test cable TC-2348 with a known-good cable, repeat the verification sweep\n"
            "  4. Substitute the through-line standard, repeat\n"
            "  5. Power-cycle the analyzer, allow 60 min warm-up, repeat sweep\n\n"
            "Report results back. If items 1-3 narrow the issue to a single component (cable or connector), the on-site "
            "engineer can bring the replacement directly. If the analyzer itself is suspect, the engineer will run "
            "internal-cal verification on-site.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 1290, "body": (
            "Ran the checklist this morning. Results:\n\n"
            "  1. Visual inspection: minor pin recession on Port 2 male connector, female side looks clean\n"
            "  2. Torque check: all connections were at 8 in-lbs\n"
            "  3. Substituting test cable: drift reduced from +0.18 dB to +0.11 dB, still outside spec\n"
            "  4. Substituting through-line: no material change from step 3\n"
            "  5. After power cycle and 60-min warm-up: drift was +0.13 dB on first sweep, stabilized at +0.11 dB after 2 hours\n\n"
            "Conclusion: probably the Port 2 connector pin recession + degraded test cable contribution. "
            "Send a replacement Port 2 connector kit and a new precision 2.4 mm cable with the engineer.\n\nPriya"), "attachments": []},
        {"from": "csr", "delay_min": 38, "body": (
            "Good diagnostic work. Adding to Doug's parts list for Friday:\n\n"
            "  - 1x 85058-60005 Port 2 N-type male replacement connector kit\n"
            "  - 1x 85133E precision 2.4 mm flex cable, 1.0 m, NMD-2.4mm to NMD-2.4mm\n"
            "  - 1x 85058-60001 torque wrench, 8 in-lbs, 5/16 in\n\n"
            "Doug will perform: Port 2 connector replacement, full S-parameter calibration verification, as-left report. "
            "Total on-site estimate: 4 to 5 hours. Bench fee for emergency dispatch is $2,200, parts at list, calibration "
            "service at standard service rate ($1,850 for Z540.3 recal). Pre-approved against your service contract "
            "SC-VERTEX-Q-053-2025-001 with $980 of co-pay applied to the bench fee.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 70, "body": (
            "Approved on the parts list and the cost breakdown. One thing — Doug arrives 08:30, but our lab security "
            "process requires escort for first-time visitors. I will arrange the escort, but please send Doug's photo ID "
            "and badge details by EOD Thursday so we can pre-clear him at the gate.\n\nPriya"), "attachments": []},
        {"from": "csr", "delay_min": 19, "body": (
            "Doug's pre-clearance package sent to your lab.access@vertex-quantum.com address as a separate email — includes "
            "passport-style photo, badge number, vehicle license plate (rental), and ETA. He will check in at the main gate "
            "by 08:25 to allow time for escort coordination.\n\nZBrain Sales Ops Desk"), "attachments": []},
        {"from": "buyer", "delay_min": 4500, "body": (
            "Service complete. Doug was efficient — replaced the Port 2 connector, swapped in the new cable, ran full "
            "calibration verification. As-left now within +/-0.03 dB across 18 to 26 GHz, well inside spec. Cal cert "
            "in-hand. We are back in business; qubit characterization run starts Monday.\n\nThanks for the fast turnaround.\nPriya"), "attachments": []},
        {"from": "csr", "delay_min": 26, "body": (
            "Excellent. Logging WO-VERTEX-Q-053-EMERG-2026-0515 as completed. New cal cert CC-VERTEX-2026-0515 supersedes "
            "CC-VERTEX-2026-0211; service contract SC-VERTEX-Q-053-2025-001 utilization updated. Sending invoice for the "
            "bench fee co-pay ($980), parts ($1,560), and calibration service ($1,850) — total $4,390, Net 30 from today. "
            "PDF copy of the cert is in your service portal.\n\n"
            "Doug noted in his service report that the Port 2 connector pin recession was consistent with high mate/demate "
            "cycle counts. We recommend reducing daily mate/demate on Port 2 by using the new precision flex cable as a "
            "permanent extension. Will avoid this issue recurring.\n\nZBrain Sales Ops Desk"), "attachments": []},
        # ... continued (16 more messages of follow-on diagnostic refinement and credit-memo cycle)
        {"from": "buyer", "delay_min": 22500, "body": "Good tip on the flex extension; we are implementing it. Quick "
            "follow-up: noticed Port 2 starting to drift again, +0.05 dB but inside spec. Is this an early warning?\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 44, "body": "0.05 dB within 6 weeks of recalibration is unusual but inside spec. "
            "Recommend running the diagnostic checklist again on schedule, plus shipping us TC-2348 for bench-level inspection.\nZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 11200, "body": "TC-2348 shipped today via FedEx, tracking 7748-2231-9914. "
            "Please advise on findings.\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 8650, "body": "TC-2348 inspection complete. Findings: minor outer-conductor "
            "bend at the SMA connector end, which would explain the gradual drift. We are issuing a replacement cable under "
            "warranty (no cost). New cable ships from Santa Rosa on Monday.\nZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 4500, "body": "Replacement cable received and in use. Drift is back to baseline. "
            "Closing this loop — thanks for the responsive service.\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 18, "body": "Glad it cleared. CCC request CCC-VERTEX-Q-053-CAL-0211 marked closed. "
            "Annual cal renewal SC-VERTEX-Q-053 is due 2027-02-11; calendar invite for renewal review in January 2027 incoming.\n"
            "ZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 33000, "body": "Hi team, separate question against the same service contract. "
            "We are adding a second PNA-X to the lab next quarter — can we add it under SC-VERTEX-Q-053-2025-001 mid-cycle?\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 22, "body": "Yes, mid-cycle additions are supported. We can pro-rate the second "
            "unit from the date of receipt through the existing contract expiry (2027-02-10), or you can opt for a fresh "
            "12-month period starting from the second unit's commissioning date. Pro-rate is typically simpler for "
            "accounting. Want me to prepare both options for your review?\nZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 880, "body": "Pro-rate is cleaner. Please send the proposal once we have the "
            "second unit's serial. ETA on the second unit is 2026-08-15.\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 26, "body": "Got it. I will set a reminder for 2026-08-01 to draft the pro-rate "
            "addendum to SC-VERTEX-Q-053-2025-001. The addendum will be ready for your review by 2026-08-10.\nZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 86400, "body": "Hi team — second PNA-X just arrived, serial SN-849177-KS. "
            "Ready for the contract addendum.\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 18, "body": "Drafting addendum CA-VERTEX-Q-053-2026-A01. Pro-rate calculation: "
            "180 days remaining on the contract, second-unit cost = $980 (180/365 of $1,985 annual coverage). Net add to "
            "the invoice on the next billing cycle.\nZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 240, "body": "Approved. Send the signed addendum to my email and to accounts.payable@vertex-quantum.com.\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 33, "body": "Done — addendum sent. Second unit now under coverage effective today. "
            "Service portal updated; you should see both units listed under SC-VERTEX-Q-053-2025-001 within the hour.\n"
            "ZBrain Sales Ops Desk", "attachments": []},
        {"from": "buyer", "delay_min": 5400, "body": "Confirmed both units now showing in the service portal. Thanks "
            "for the smooth coordination on this entire thread — calibration emergency, replacement parts, warranty cable, "
            "and contract addendum all handled cleanly across what is now 4 months of correspondence. Closing this final "
            "loop.\nPriya", "attachments": []},
        {"from": "csr", "delay_min": 19, "body": "Likewise glad to have the thread land cleanly. Sending a summary "
            "transcript of all 28 messages to your records inbox for compliance / audit purposes. Have a great rest "
            "of the quarter.\nZBrain Sales Ops Desk", "attachments": []},
    ],
}


# ---------------------------------------------------------------------------
# Scenario 3 — Bluehawk · export compliance + legal review · 32 messages · EN
# ---------------------------------------------------------------------------

BLUEHAWK_EXPORT_LONG_EN: dict[str, Any] = {
    "key": "bluehawk_export_long_en",
    "customer_code": "BLUEH-DEF-021",
    "language": "en",
    "subject_root": "PO-BLUEH-2026-0455 — 67 GHz PNA-X + UXR oscilloscope, export classification review",
    "intent_hint": "po_intake",
    "messages": [
        # 32 messages: PO -> compliance review -> legal interpretation -> license app -> approval -> book
        {"from": "buyer", "delay_min": 0, "body": (
            "Hi ZBrain Sales Ops,\n\n"
            "PO PO-BLUEH-2026-0455 attached. Order for our Arlington VA defense electronics lab:\n\n"
            "  Line 1 — 2x N5247B-419 PNA-X, 67 GHz\n"
            "  Line 2 — 1x UXR0334A Infiniium UXR Oscilloscope, 33 GHz\n"
            "  Line 3 — 1x M8040A High-Performance BERT, 64 GBaud\n\n"
            "All units are tagged as ITAR-controlled at our end. Our compliance team needs ECCN, country-of-origin, and "
            "end-user statement coordination before we can release this PO to production.\n\n"
            "Aaron Brewer, Calibration Lab Supervisor"), "attachments": []},
        {"from": "csr", "delay_min": 28, "body": "Hi Aaron, acknowledged. Routing to our export compliance team now. "
            "Initial classification on file: PNA-X is 3A002.f, UXR is 3A002.a.5, BERT is 3A002.a.5. End-use review will "
            "kick off the moment we get your end-user statement. Compliance team will reach out within 4 hours.\nZBrain Sales Ops", "attachments": []},
    ] + [
        {"from": ("buyer" if i % 2 == 0 else "csr"), "delay_min": 60 + i * 18,
         "body": f"[Message {i+3} of 32 in the export-compliance review thread — detailed back-and-forth on end-user "
                f"certification (ECCN 3A002.f), license application status, BIS response, country-of-origin "
                f"verification, and final release to production. Full content body for message {i+3}.]"} for i in range(30)
    ],
}


# ---------------------------------------------------------------------------
# Scenario 4 — Meridian Comunicaciones · Spanish multi-asset PO · 24 messages
# ---------------------------------------------------------------------------

MERIDIAN_MULTI_ASSET_ES: dict[str, Any] = {
    "key": "meridian_multi_asset_es",
    "customer_code": "MERID-COMM-077",
    "language": "es",
    "subject_root": "PO-MERID-2026-0817 — pedido multi-activo, 6 instrumentos para campo anecoico",
    "intent_hint": "po_intake",
    "messages": [
        {"from": "buyer", "delay_min": 0, "body": (
            "Hola ZBrain Sales Ops,\n\n"
            "Adjunto pedido PO-MERID-2026-0817 para nuestra nueva campana anecoica en Alcobendas. Son 6 instrumentos:\n\n"
            "  Linea 1 — 2x M9384B-04F VXG Vector Signal Generator, 44 GHz\n"
            "  Linea 2 — 1x N9040B-550 UXA Signal Analyzer, 50 GHz\n"
            "  Linea 3 — 2x N5247B-485 PNA-X, 67 GHz con Pulse Option\n"
            "  Linea 4 — 1x N9952A FieldFox Handheld 50 GHz\n\n"
            "Como es multi-activo, necesitamos un CCC por activo segun nuestro procedimiento interno. Confirme por "
            "favor que el sistema generara 6 CCC separados, uno por cada Serial/Model.\n\n"
            "Saludos,\nMariela Solis"), "attachments": []},
        {"from": "csr", "delay_min": 24, "body": (
            "Hola Mariela,\n\n"
            "Pedido recibido. Confirmo: el sistema generara 6 CCC separados — uno por cada combinacion Model/Serial — "
            "siguiendo nuestro procedimiento de fan-out multi-activo:\n\n"
            "  CCC-MERID-2026-0817-001 = M9384B-04F (Serial pendiente)\n"
            "  CCC-MERID-2026-0817-002 = M9384B-04F (Serial pendiente)\n"
            "  CCC-MERID-2026-0817-003 = N9040B-550 (Serial pendiente)\n"
            "  CCC-MERID-2026-0817-004 = N5247B-485 (Serial pendiente)\n"
            "  CCC-MERID-2026-0817-005 = N5247B-485 (Serial pendiente)\n"
            "  CCC-MERID-2026-0817-006 = N9952A (Serial pendiente)\n\n"
            "Los seriales se asignan cuando los equipos salen de fabrica. Plazos de entrega ex-works: "
            "M9384B-04F 16 semanas, N9040B-550 14 semanas, N5247B-485 18 semanas, N9952A 8 semanas.\n\n"
            "Saludos,\nZBrain Sales Ops Desk"), "attachments": []},
    ] + [
        {"from": ("buyer" if i % 2 == 0 else "csr"), "delay_min": 100 + i * 30,
         "body": f"[Mensaje {i+3} de 24 en hilo multi-activo: coordinacion de plazos, asignacion de seriales por activo, "
                f"calibracion individual ISO 17025, envio agrupado, documentacion bilingue.]"} for i in range(22)
    ],
}


# ---------------------------------------------------------------------------
# Scenario 5 — Aurora Auto · shipping damage escalation · 40 messages · EN
# ---------------------------------------------------------------------------

AURORA_SHIPPING_LONG_EN: dict[str, Any] = {
    "key": "aurora_shipping_long_en",
    "customer_code": "AURA-AUTO-119",
    "language": "en",
    "subject_root": "Damaged-on-Arrival — UXR Oscilloscope SO-AURA-2026-2102, request replacement + RMA + insurance claim",
    "intent_hint": "wo_update_request",
    "messages": [
        {"from": "buyer", "delay_min": 0, "body": (
            "Hi ZBrain Sales Ops,\n\n"
            "Reporting damage on the UXR0334A oscilloscope from order SO-AURA-2026-2102. Photos attached.\n\n"
            "Receiving inspection at our Auburn Hills EE lab this morning found: chassis dented on the lower-left rear, "
            "front panel BNC connector for Channel 2 bent, internal alignment beep test fails. Shipping crate "
            "was visibly compromised — fork-truck mark on one side.\n\n"
            "Need an RMA + replacement asap. Q3 SAE testbed depends on this unit.\n\n"
            "Tom Reilly, EE Test Lead"), "attachments": []},
        {"from": "csr", "delay_min": 19, "body": (
            "Hi Tom, acknowledged and escalating. Issuing RMA-AURA-2026-2102-01 in parallel. Couple of immediate questions:\n\n"
            "  - Was the damage visible at unboxing (i.e., before powering up)?\n"
            "  - Did the receiving team document the crate condition and refuse delivery, or was it accepted with damage notes?\n"
            "  - Carrier: was it our preferred logistics (UPS Special Handling)?\n\n"
            "These answers determine whether the claim goes through our insurance (best case) or carrier liability "
            "(slower). Replacement timing depends.\n\nZBrain Sales Ops"), "attachments": []},
    ] + [
        {"from": ("buyer" if i % 2 == 0 else "csr"), "delay_min": 90 + i * 22,
         "body": f"[Message {i+3} of 40: shipping-damage escalation — photos, BOL review, insurance carrier negotiation, "
                f"loaner unit dispatch, RMA process, replacement unit production slot, calibration verification, "
                f"acceptance test, root-cause review with logistics partner.]"} for i in range(38)
    ],
}


# ---------------------------------------------------------------------------
# Registry — append these into seed_threads.SCENARIOS
# ---------------------------------------------------------------------------

EXTRA_SCENARIOS: list[dict[str, Any]] = [
    OZEKI_PO_LONG_EN,
    VERTEX_CAL_ESCALATION_EN,
    BLUEHAWK_EXPORT_LONG_EN,
    MERIDIAN_MULTI_ASSET_ES,
    AURORA_SHIPPING_LONG_EN,
]

"""Pipeline stress-test script.

Fires N emails through the pipeline batch endpoint to demonstrate concurrent
throughput. Reports submission rate, queue snapshot, and final outcomes.

The RFP commits to:
  - 2,000 emails per day baseline (~33 / minute, ~0.55 / second)
  - 5x quarter-end burst (~10,000 / day, ~167 / minute)
  - 50x stress test (~100,000 / day, ~1,667 / minute, ~28 / second)

Usage:
    python scripts/stress_test.py                  # 100 emails, default
    python scripts/stress_test.py --emails 500     # 500 emails
    python scripts/stress_test.py --emails 2000    # full daily baseline
    python scripts/stress_test.py --emails 2000 --burst 5x   # 5x burst
    python scripts/stress_test.py --watch          # tail the queue until drained

The script picks email_ids from the local DB at random so the same script
works against any seeded environment (138 emails or 1,000 doesn't matter —
the pool re-uses email rows by submitting them repeatedly with a fresh
Pipeline row each time, mirroring real inbound behaviour where the same
mailbox keeps receiving new mail).
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

# Ensure backend root is on the path when invoked as `python scripts/stress_test.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress-test the pipeline worker pool.")
    parser.add_argument("--emails", type=int, default=100, help="Total emails to submit (default: 100)")
    parser.add_argument(
        "--burst", default="1x",
        choices=["1x", "5x", "50x", "100x"],
        help="Submission rate multiplier — 1x=2000/day baseline, 5x=quarter-end, 50x=stress",
    )
    parser.add_argument(
        "--host", default="http://127.0.0.1:8000",
        help="Backend host (default: http://127.0.0.1:8000)",
    )
    parser.add_argument("--watch", action="store_true",
        help="Continue polling /queue-status until queue drains")
    parser.add_argument("--chunk-size", type=int, default=25,
        help="Number of emails per batch POST (default: 25)")
    args = parser.parse_args()

    # Target submission rates (emails per second).
    rate_map = {"1x": 0.55, "5x": 2.78, "50x": 27.8, "100x": 55.6}
    target_rate = rate_map[args.burst]

    client = httpx.Client(base_url=args.host, timeout=60.0)

    # Discover seeded email_ids.
    print(f"Discovering seeded emails on {args.host}...")
    r = client.get("/api/emails", params={"limit": 5000})
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, list):
        emails = payload
    elif isinstance(payload, dict):
        emails = payload.get("emails") or []
    else:
        emails = []
    if not emails:
        print("ERROR: no emails found in seed; run /api/seed/reset first.", file=sys.stderr)
        return 2
    email_ids = [e.get("id") for e in emails if e.get("id")]
    print(f"Found {len(email_ids)} seeded emails. Building submission list of {args.emails} (with replacement).")

    submission_list = [random.choice(email_ids) for _ in range(args.emails)]
    chunks: list[list[int]] = []
    for i in range(0, len(submission_list), args.chunk_size):
        chunks.append(submission_list[i : i + args.chunk_size])

    # Snapshot before
    print(f"\nTarget: {args.emails} emails @ {target_rate:.2f} emails/sec ({args.burst}) → {len(chunks)} chunk(s) of {args.chunk_size}")
    print(f"Pre-test queue: {client.get('/api/pipelines/queue-status').json()}")

    started_at = time.perf_counter()
    submitted_count = 0
    for idx, chunk in enumerate(chunks):
        chunk_start = time.perf_counter()
        r = client.post("/api/pipelines/run-batch", json={"email_ids": chunk})
        r.raise_for_status()
        body = r.json()
        submitted_count += len(body.get("submitted", []))
        snap = body.get("queue_snapshot", {})
        in_flight = snap.get("in_flight", 0)
        completed = snap.get("completed", 0)
        elapsed = time.perf_counter() - started_at
        actual_rate = submitted_count / elapsed if elapsed > 0 else 0.0
        print(
            f"  [chunk {idx + 1}/{len(chunks)}] submitted={len(body['submitted']):3d}  "
            f"in_flight={in_flight:3d}  completed={completed:5d}  "
            f"actual_rate={actual_rate:.1f}/s"
        )
        # Pace to target rate
        chunk_target_time = len(chunk) / target_rate
        chunk_elapsed = time.perf_counter() - chunk_start
        sleep_for = max(0.0, chunk_target_time - chunk_elapsed)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"\nAll {submitted_count} emails submitted in {time.perf_counter() - started_at:.2f}s.")

    if args.watch:
        print("\nWatching queue until drained...")
        last_in_flight = -1
        while True:
            status = client.get("/api/pipelines/queue-status").json()
            in_flight = status.get("in_flight", 0)
            completed = status.get("completed", 0)
            errored = status.get("errored", 0)
            lat = status.get("latency_ms") or {}
            if in_flight != last_in_flight:
                print(
                    f"  in_flight={in_flight:3d}  completed={completed:5d}  "
                    f"errored={errored:3d}  p50={lat.get('p50'):>5}ms  "
                    f"p95={lat.get('p95'):>5}ms  p99={lat.get('p99'):>5}ms"
                )
            last_in_flight = in_flight
            if in_flight == 0:
                print(f"\nDrained. Final status: {status}")
                break
            time.sleep(2)

    return 0


if __name__ == "__main__":
    sys.exit(main())

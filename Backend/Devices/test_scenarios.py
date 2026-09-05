"""Controlled-test CLI: send one deliberately-shaped message at the hub's
ingestion gateway (`/ws/ingest`) and report exactly what the server did.

This is the single-shot counterpart to `Backend/Devices/cameras.py`'s
continuous simulator. It intentionally reuses that module's payload shape
and scenario vocabulary rather than inventing a second architecture — see
`Backend/Devices/cameras.py`'s `ScenarioController` for the equivalent
continuous-mode corruptions (`spike`/`drop`/`missing_data`/... driven by
`TCMS_SIMULATOR_ANOMALY_MODE`). Protocol-level scenarios that aren't
"traffic shapes" (invalid JSON, invalid structure, wrong device_id) only
make sense as a one-shot message, which is what this module adds.

Usage:
    python -m Backend.Devices.test_scenarios --list
    python -m Backend.Devices.test_scenarios --scenario normal
    python -m Backend.Devices.test_scenarios --scenario missing
    python -m Backend.Devices.test_scenarios --scenario invalid-json
    python -m Backend.Devices.test_scenarios --scenario invalid-structure
    python -m Backend.Devices.test_scenarios --scenario wrong-device
    python -m Backend.Devices.test_scenarios --scenario spike
    python -m Backend.Devices.test_scenarios --scenario drop
    python -m Backend.Devices.test_scenarios --scenario negative
    python -m Backend.Devices.test_scenarios --scenario timestamp --variant malformed
    python -m Backend.Devices.test_scenarios --scenario timestamp --variant future
    python -m Backend.Devices.test_scenarios --scenario timestamp --variant duplicate
    python -m Backend.Devices.test_scenarios --scenario timestamp --variant out-of-order

Or, from the host, via the running `simulator` container:
    docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario spike
"""

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

NORMAL_COUNTS = {"سواری": 20, "کامیون": 3, "موتور": 8, "اتوبوس": 2, "وانت": 5}
SPIKE_COUNTS = {"سواری": 1000, "کامیون": 500, "موتور": 800, "اتوبوس": 400, "وانت": 600}
DROP_COUNTS = {"سواری": 0, "کامیون": 0, "موتور": 0, "اتوبوس": 0, "وانت": 0}
NEGATIVE_COUNTS = {"سواری": -10, "کامیون": 3, "موتور": 5, "اتوبوس": 1, "وانت": 2}

TIMESTAMP_VARIANTS = ("malformed", "future", "duplicate", "out-of-order")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload(
    device_id: str,
    counts: dict,
    timestamp: Optional[str] = None,
    location_type: str = "urban",
    interval_minutes: int = 5,
) -> dict:
    return {
        "device_id": device_id,
        "location_type": location_type,
        "timestamp": timestamp or _now_iso(),
        "interval_minutes": interval_minutes,
        "counts": counts,
    }


async def _send_and_observe(url: str, messages: list[str], label: str) -> None:
    """Connects once, sends every message in `messages` in order, then keeps
    the socket open for a moment to see whether the server closed it —
    reproducing exactly what the real ingestion gateway does, not a
    fabricated response (the gateway is fire-and-forget per message; see
    `Backend/app/domains/ingestion/router.py`)."""
    print(f"=== scenario: {label} ===")
    print(f"connecting to {url}")
    try:
        async with websockets.connect(url) as ws:
            print("✓ connection accepted (device_id/token authenticated)")
            for message in messages:
                await ws.send(message)
                print(f"  → sent: {message}")
            try:
                await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            except ConnectionClosed as exc:
                print(f"✗ server closed the connection: code={exc.code} reason={exc.reason!r}")
                return
            print("✓ connection still open after send — server did not crash")
    except ConnectionClosed as exc:
        print(f"✗ connection rejected/closed at handshake: code={exc.code} reason={exc.reason!r}")
    print(
        "Check the dashboard/API to see the actual outcome, e.g.:\n"
        "  GET /records/{device_id}/history\n"
        "  GET /alerts?unacknowledged_only=true\n"
        "  GET /ml/devices/{device_id}/anomalies\n"
    )


def _scenario_normal(device_id: str) -> tuple[list[str], str]:
    payload = _payload(device_id, NORMAL_COUNTS)
    return [json.dumps(payload, ensure_ascii=False)], (
        "Well-formed payload with plausible counts. Expected: accepted, stored, "
        "device marked online, no anomaly."
    )


def _scenario_spike(device_id: str) -> tuple[list[str], str]:
    payload = _payload(device_id, SPIKE_COUNTS)
    return [json.dumps(payload, ensure_ascii=False)], (
        "Extreme traffic counts far above any historical baseline. Expected: "
        "the statistical z-score check and/or the ML quick_score rule "
        "violations flag this as anomalous, an alert is raised, and the "
        "record is stored with anomaly_flag=true (see GET /ml/devices/"
        f"{device_id}/anomalies)."
    )


def _scenario_drop(device_id: str) -> tuple[list[str], str]:
    payload = _payload(device_id, DROP_COUNTS)
    return [json.dumps(payload, ensure_ascii=False)], (
        "All-zero counts. Structurally valid (zero is not negative), so it "
        "is accepted and stored; whether it is flagged anomalous depends on "
        "the device's historical baseline and the ML quick_score rule set "
        "(total-collapse check) — inspect the stored record's anomaly_flag "
        "and anomaly_reason, don't assume."
    )


def _scenario_negative(device_id: str) -> tuple[list[str], str]:
    payload = _payload(device_id, NEGATIVE_COUNTS)
    return [json.dumps(payload, ensure_ascii=False)], (
        "Negative count. `validate_structure` rejects any negative count "
        "outright (Backend/app/domains/ingestion/validation.py). Expected: "
        "rejected before being stored, an `invalid_payload` alert is raised, "
        "and an `ingest_rejected` audit_log entry is written. No database "
        "row is created for this message."
    )


def _scenario_invalid_json(device_id: str) -> tuple[list[str], str]:
    return ["{invalid-json"], (
        "Not valid JSON. Expected: `json.loads` fails inside "
        "`handle_message`, an `invalid_payload` alert is raised, and the "
        "WebSocket connection is NOT closed — the ingestion loop keeps "
        "running for this and every other device."
    )


def _scenario_invalid_structure(device_id: str) -> tuple[list[str], str]:
    payload = {"device_id": device_id, "foo": "bar"}
    return [json.dumps(payload, ensure_ascii=False)], (
        "Valid JSON but missing required fields (timestamp, counts). "
        "Expected: `validate_structure` raises ValidationError, an "
        "`invalid_payload` alert is raised, and an `ingest_rejected` "
        "audit_log entry is written. No database row is created."
    )


def _scenario_wrong_device(device_id: str, payload_device_id: str) -> tuple[list[str], str]:
    payload = _payload(payload_device_id, NORMAL_COUNTS)
    return [json.dumps(payload, ensure_ascii=False)], (
        f"Connected as '{device_id}' but the payload claims to be "
        f"'{payload_device_id}'. Expected: `handle_message` detects the "
        "device_id mismatch, raises an `invalid_payload` alert, and drops "
        "the record — nothing is persisted as valid traffic data for "
        f"either device."
    )


def _scenario_timestamp(device_id: str, variant: str) -> tuple[list[str], str]:
    if variant == "malformed":
        payload = _payload(device_id, NORMAL_COUNTS, timestamp="not-a-real-timestamp")
        note = (
            "Unparseable timestamp string. Expected: `validate_structure` "
            "raises ValidationError (`unparseable timestamp`), rejected, "
            "alert + audit `ingest_rejected`."
        )
    elif variant == "future":
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        payload = _payload(device_id, NORMAL_COUNTS, timestamp=future)
        note = (
            "Timestamp 1 hour in the future (beyond the 5-minute clock-skew "
            "tolerance, MAX_CLOCK_SKEW in ingestion/validation.py). Expected: "
            "rejected as 'timestamp too far in the future'."
        )
    elif variant == "duplicate":
        same = _now_iso()
        payload_a = _payload(device_id, NORMAL_COUNTS, timestamp=same)
        payload_b = _payload(device_id, {**NORMAL_COUNTS, "سواری": 999}, timestamp=same)
        return (
            [
                json.dumps(payload_a, ensure_ascii=False),
                json.dumps(payload_b, ensure_ascii=False),
            ],
            (
                "Two messages with the identical timestamp. `traffic_records` "
                "has a composite primary key (device_id, timestamp) and "
                "`upsert_ingested` uses `ON CONFLICT ... DO UPDATE` — expected: "
                "both are accepted, the second silently overwrites the first "
                "(no rejection, no duplicate-specific alert; this is the "
                "actual implemented behaviour, not an assumption)."
            ),
        )
    elif variant == "out-of-order":
        earlier = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        payload = _payload(device_id, NORMAL_COUNTS, timestamp=earlier)
        note = (
            "A timestamp 30 minutes earlier than 'now', sent after later "
            "readings. There is no explicit monotonic-ordering check in "
            "`validate_structure` (only the future/backdate bounds) — "
            "expected: accepted and stored at its own timestamp like any "
            "other in-range reading."
        )
    else:
        raise SystemExit(f"unknown --variant {variant!r}, choose from {TIMESTAMP_VARIANTS}")
    return [json.dumps(payload, ensure_ascii=False)], note


async def _scenario_missing() -> None:
    """Missing-interval / reconstruction is not a message shape — it's the
    *absence* of one. Rather than fabricate a fake wait, this triggers the
    real reconstruction engine pass immediately (the same function the
    background worker calls every `TCMS_RECONSTRUCTION_SCAN_INTERVAL_SECONDS`)
    and prints what it actually found."""
    from Backend.app.db import pool as db_pool
    from Backend.app.domains.reconstruction.engine import run_once
    from Backend.app.domains.reconstruction.service import list_log

    print("=== scenario: missing ===")
    print(
        "This scenario does not send a message — a missing interval is the "
        "absence of one. To observe it: stop (or don't start) a device's "
        "simulator connection for one interval, then this command runs the "
        "real reconstruction engine pass immediately (rather than waiting "
        "for the scheduled worker) and prints what it found.\n"
    )
    pool = await db_pool.connect()
    try:
        filled = await run_once(pool)
        print(f"reconstruction pass filled {filled} record(s)")
        rows = await list_log(pool, None, 5)
        if not rows:
            print("reconstruction_log is empty — no gap was found to fill yet.")
        for row in rows:
            print(
                f"  device={row['device_id']} timestamp={row['timestamp']} "
                f"method={row['method']} manual_override={row['manual_override']}"
            )
    finally:
        await db_pool.disconnect()


SCENARIOS = {
    "normal": "Well-formed payload; should be accepted with no anomaly.",
    "missing": "Trigger an immediate reconstruction pass for a missed interval.",
    "invalid-json": "Malformed JSON; should be rejected without crashing the socket.",
    "invalid-structure": "Valid JSON, missing required fields; should be rejected.",
    "wrong-device": "Payload device_id differs from the connection's device_id.",
    "spike": "Extreme counts; should trigger anomaly detection.",
    "drop": "All-zero counts; inspect whether it's flagged anomalous.",
    "negative": "Negative count value; must be rejected by validation.",
    "timestamp": "Malformed/future/duplicate/out-of-order timestamp (--variant).",
}


def _hub_ws_url() -> str:
    return os.environ.get("TCMS_HUB_WS_URL", "ws://localhost:8000/ws/ingest")


def _token() -> str:
    return os.environ.get("TCMS_DEVICE_TOKEN", "change-me-device-token")


async def _run(args: argparse.Namespace) -> None:
    if args.scenario == "missing":
        await _scenario_missing()
        return

    url = f"{_hub_ws_url()}?device_id={args.device_id}&token={_token()}"

    if args.scenario == "normal":
        messages, note = _scenario_normal(args.device_id)
    elif args.scenario == "spike":
        messages, note = _scenario_spike(args.device_id)
    elif args.scenario == "drop":
        messages, note = _scenario_drop(args.device_id)
    elif args.scenario == "negative":
        messages, note = _scenario_negative(args.device_id)
    elif args.scenario == "invalid-json":
        messages, note = _scenario_invalid_json(args.device_id)
    elif args.scenario == "invalid-structure":
        messages, note = _scenario_invalid_structure(args.device_id)
    elif args.scenario == "wrong-device":
        messages, note = _scenario_wrong_device(args.device_id, args.payload_device_id)
    elif args.scenario == "timestamp":
        messages, note = _scenario_timestamp(args.device_id, args.variant)
    else:
        raise SystemExit(f"unknown scenario {args.scenario!r}")

    print(note, "\n")
    await _send_and_observe(url, messages, args.scenario)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS))
    parser.add_argument(
        "--device-id",
        default="cam-01",
        help="device_id to authenticate the WebSocket connection as (must be "
        "a registered device; the seed migration registers cam-01..cam-05)",
    )
    parser.add_argument(
        "--payload-device-id",
        default="cam-99",
        help="only for --scenario wrong-device: the device_id claimed inside "
        "the payload itself",
    )
    parser.add_argument(
        "--variant",
        default="malformed",
        choices=TIMESTAMP_VARIANTS,
        help="only for --scenario timestamp",
    )
    args = parser.parse_args()

    if args.list or not args.scenario:
        print("Available scenarios:\n")
        for name, desc in SCENARIOS.items():
            print(f"  {name:<20} {desc}")
        print(
            "\nExample:\n"
            "  python -m Backend.Devices.test_scenarios --scenario spike\n"
            "  docker compose exec simulator python -m Backend.Devices.test_scenarios --scenario spike"
        )
        return

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

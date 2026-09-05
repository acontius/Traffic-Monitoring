"""End-to-end demo runner: exercises the full ingestion -> validation ->
anomaly/ML -> alert -> reconstruction -> forwarding -> report pipeline in
one command and prints the real, live API responses at every stage — no
fabricated output.

Usage:
    python -m Backend.Devices.demo
    docker compose exec simulator python -m Backend.Devices.demo

Requires the `app` service to be reachable (derives the REST base URL from
`TCMS_HUB_WS_URL`, e.g. ws://app:8000/ws/ingest -> http://app:8000) and an
admin account to exist (`TCMS_ADMIN_USERNAME`/`TCMS_ADMIN_PASSWORD`, created
via `python -m Backend.scripts.create_admin` if it doesn't yet).
"""

import asyncio
import json
import os
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets

from Backend.Devices.test_scenarios import (
    NORMAL_COUNTS,
    SPIKE_COUNTS,
    _payload,
)

DEMO_DEVICE_ID = os.environ.get("TCMS_DEMO_DEVICE_ID", "cam-01")


def _hub_ws_url() -> str:
    return os.environ.get("TCMS_HUB_WS_URL", "ws://localhost:8000/ws/ingest")


def _device_token() -> str:
    return os.environ.get("TCMS_DEVICE_TOKEN", "change-me-device-token")


def _rest_base_url() -> str:
    parts = urlsplit(_hub_ws_url())
    scheme = "https" if parts.scheme == "wss" else "http"
    return urlunsplit((scheme, parts.netloc, "", "", ""))


async def _send_ws_message(payload: dict) -> None:
    url = f"{_hub_ws_url()}?device_id={DEMO_DEVICE_ID}&token={_device_token()}"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
    await asyncio.sleep(0.3)  # give the server a moment to finish handle_message


async def _login(client: httpx.AsyncClient) -> str:
    username = os.environ.get("TCMS_ADMIN_USERNAME", "admin")
    password = os.environ.get("TCMS_ADMIN_PASSWORD")
    if not password:
        raise SystemExit(
            "TCMS_ADMIN_PASSWORD is not set — set it or run "
            "`python -m Backend.scripts.create_admin` first."
        )
    response = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def _ok(detail: str) -> None:
    print(f"    ✓ {detail}")


def _warn(detail: str) -> None:
    print(f"    ! {detail}")


async def run_demo() -> None:
    print("=== TCMS DEMO ===")
    print(f"device: {DEMO_DEVICE_ID}   backend: {_rest_base_url()}")

    async with httpx.AsyncClient(base_url=_rest_base_url(), timeout=15) as client:
        token = await _login(client)
        client.headers["Authorization"] = f"Bearer {token}"

        _step(1, "Normal input")
        await _send_ws_message(_payload(DEMO_DEVICE_ID, NORMAL_COUNTS))
        history = await client.get(f"/records/{DEMO_DEVICE_ID}/history", params={"limit": 1})
        history.raise_for_status()
        latest = history.json()[0] if history.json() else None
        if latest:
            _ok(f"accepted, stored (anomaly_flag={latest['anomaly_flag']})")
        else:
            _warn("no record found in history after send")

        _step(2, "Anomalous input (spike)")
        await _send_ws_message(_payload(DEMO_DEVICE_ID, SPIKE_COUNTS))
        anomalies = await client.get(
            f"/ml/devices/{DEMO_DEVICE_ID}/anomalies", params={"limit": 1}
        )
        anomalies.raise_for_status()
        events = anomalies.json()
        history2 = await client.get(f"/records/{DEMO_DEVICE_ID}/history", params={"limit": 1})
        latest2 = history2.json()[0] if history2.json() else None
        if events:
            top = events[0]
            _ok(
                f"anomaly detected (type={top['anomaly_type']}, "
                f"score={top['score']:.2f}, severity={top['severity']})"
            )
        elif latest2 and latest2.get("anomaly_flag"):
            _ok(f"anomaly detected: {latest2.get('payload', {})}")
        else:
            _warn(
                "no anomaly event recorded yet — the ML layer may still be "
                "scoring in the background, or this device's history is too "
                "short for the statistical baseline to trigger"
            )

        _step(3, "Missing interval + reconstruction")
        from Backend.app.db import pool as db_pool
        from Backend.app.domains.reconstruction.engine import run_once

        pool = await db_pool.connect()
        try:
            filled = await run_once(pool)
        finally:
            await db_pool.disconnect()
        _ok(f"reconstruction pass ran ({filled} record(s) filled this pass)")

        recon = await client.get(
            "/reconstruction/log", params={"device_id": DEMO_DEVICE_ID, "limit": 1}
        )
        recon.raise_for_status()
        recon_rows = recon.json()

        _step(4, "Reconstruction detail")
        if recon_rows:
            row = recon_rows[0]
            _ok(f"method={row['method']} manual_override={row['manual_override']}")
        else:
            _warn(
                "no reconstruction_log entry for this device yet — nothing "
                "was missing this pass (run this demo again after stopping "
                "the device's simulator for one interval to see a real gap)"
            )

        _step(5, "Alerts")
        alerts = await client.get("/alerts", params={"limit": 5})
        alerts.raise_for_status()
        alert_rows = alerts.json()
        if alert_rows:
            top_alert = alert_rows[0]
            _ok(f"{top_alert['type']} ({top_alert['severity']}): {top_alert['message']}")
        else:
            _warn("no alerts found")

        _step(6, "Forwarding")
        forwarding = await client.get(
            "/forwarding", params={"limit": 1}
        )
        forwarding.raise_for_status()
        fwd_rows = forwarding.json()
        if fwd_rows:
            row = fwd_rows[0]
            _ok(f"status={row['status']} attempt_count={row['attempt_count']}")
        else:
            _warn("forwarding_log is empty")

        _step(7, "Report")
        report = await client.get(
            "/reports", params={"device_id": DEMO_DEVICE_ID, "format": "json"}
        )
        report.raise_for_status()
        rows = report.json()
        _ok(f"generated ({len(rows)} row(s) for {DEMO_DEVICE_ID})")

    print("\n=== DEMO COMPLETE ===")


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()

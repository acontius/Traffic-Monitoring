"""Alert creation + delivery orchestration (SRS 3.8): persists the alert
(via the alerts domain, which owns that table), pushes it live to the
dashboard, and sends an SMS for critical severity."""

from typing import Any, Optional

import asyncpg

from Backend.app.domains.alerts import queries as alerts_queries
from Backend.app.domains.notifications.sms_client import send_sms_alert
from Backend.app.domains.realtime.bus import broadcast_alert


async def raise_alert(
    pool: asyncpg.pool.Pool,
    alert_type: str,
    message: str,
    severity: str = "info",
    device_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> int:
    row = await alerts_queries.insert_alert(
        pool, alert_type, message, severity, device_id, details
    )

    alert = {
        "id": row["id"],
        "type": alert_type,
        "device_id": device_id,
        "severity": severity,
        "message": message,
        "details": details,
        "created_at": row["created_at"].isoformat(),
    }
    await broadcast_alert(alert)

    if severity == "critical":
        await send_sms_alert(message)

    return row["id"]

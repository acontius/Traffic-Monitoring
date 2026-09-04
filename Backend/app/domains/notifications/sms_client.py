"""SMS gateway client, used for critical alerts (SRS 3.8). The gateway URL
is fully configurable (env var) so a real provider can be plugged in without
code changes; a local mock endpoint is used in dev/test."""

import logging

import httpx

from Backend.app.core.config import get_settings

logger = logging.getLogger("tcms.notifications")


async def send_sms_alert(message: str) -> bool:
    settings = get_settings()
    if not settings.sms_recipients:
        logger.warning("SMS gateway configured but no recipients set; skipping")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                settings.sms_gateway_url,
                json={"recipients": settings.sms_recipients, "message": message},
                headers=(
                    {"Authorization": f"Bearer {settings.sms_gateway_api_key}"}
                    if settings.sms_gateway_api_key
                    else {}
                ),
            )
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.error("failed to send SMS alert: %s", exc)
        return False

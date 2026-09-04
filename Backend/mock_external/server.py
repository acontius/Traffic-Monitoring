"""Local mock for the two external systems the SRS references but that
don't exist in this repo: the road-authority (راهداری) web service the hub
forwards data to, and the SMS gateway used for critical alerts.

Point `TCMS_ROAD_AUTHORITY_WEBHOOK_URL` / `TCMS_SMS_GATEWAY_URL` at this
service during development/testing; swap them for the real endpoints in
production without touching any application code.

Run: uvicorn Backend.mock_external.server:app --port 9100
"""

import logging

from fastapi import FastAPI, Request

logger = logging.getLogger("tcms.mock_external")
app = FastAPI(title="TCMS mock external services")


@app.post("/mock-road-authority")
async def mock_road_authority(request: Request):
    body = await request.json()
    logger.info("mock road-authority received: %s", body)
    return {
        "received": True,
        "device_id": body.get("device_id"),
        "timestamp": body.get("timestamp"),
    }


@app.post("/mock-sms")
async def mock_sms(request: Request):
    body = await request.json()
    logger.info(
        "mock SMS gateway would send to %s: %s",
        body.get("recipients"),
        body.get("message"),
    )
    return {"sent": True}

"""Optional OpenRouter explanation service (spec §25-§27, §43). Off by
default (`TCMS_AI_ENABLED=false`); the numerical pipeline never calls this
module, and every caller must treat its result as advisory-only narrative
text — `policy.py` has already made every decision this could describe.

Safety boundaries (spec §26): this module only ever sends the small
`AnomalyEvidence` object, never executes anything the response says, and
validates the response strictly against `schemas.Explanation` before
returning it. Any failure (disabled, no key, timeout, malformed JSON,
non-2xx) is caught and logged; callers get `None` back and continue exactly
as if AI were disabled — an LLM outage must never affect ingestion
(spec §45).
"""

import json
import logging
from typing import Optional

import httpx

from Backend.app.core.config import get_settings
from Backend.app.ml.schemas import AnomalyEvidence, Explanation

logger = logging.getLogger("tcms.ml.ai")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a traffic-operations assistant. You are given already-computed "
    "structured evidence about a possible traffic anomaly. Reply with ONLY a "
    "JSON object with exactly these keys: likely_cause (short string), "
    "explanation (1-3 sentences, based only on the given facts, no "
    "invented numbers), severity (one of info/warning/critical), and "
    "recommended_action (short string). Do not include anything else."
)


async def explain(evidence: AnomalyEvidence) -> Optional[Explanation]:
    settings = get_settings()
    if not settings.ai_enabled or not settings.openrouter_api_key:
        return None

    body = {
        "model": settings.openrouter_model or "openrouter/auto",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": evidence.model_dump_json()},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}

    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(OPENROUTER_URL, json=body, headers=headers)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return Explanation.model_validate(json.loads(content))
    except Exception:
        logger.warning(
            "OpenRouter explanation failed; continuing without it", exc_info=True
        )
        return None

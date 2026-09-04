"""Filterable reporting with CSV export (SRS 3.7)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from Backend.app.core.security import get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.reports import service

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)]
)


@router.get("")
async def get_report(
    device_id: Optional[str] = None,
    location_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    format: str = Query("json", pattern="^(json|csv)$"),
    pool=Depends(get_pool),
):
    if format == "json":
        return await service.get_json(
            pool, device_id, location_type, date_from, date_to
        )

    csv_text = await service.get_csv(pool, device_id, location_type, date_from, date_to)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=traffic_report.csv"},
    )

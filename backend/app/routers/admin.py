"""Admin router: zone management, usage visibility, and audit log."""

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LLM_PRICING, settings
from app.dependencies import get_admin_user, get_db
from app.models.chat import DailyTokenUsage
from app.models.user import User
from app.schemas.zone import (
    ZoneCreate,
    ZoneNotebookOut,
    ZoneOut,
    ZoneReorder,
    ZoneUpdate,
)
from app.services import audit_service
from app.services.zone_service import (
    ZoneValidationError,
    add_notebook,
    create_zone,
    delete_zone,
    delete_zone_notebook,
    list_zone_notebooks,
    list_zones_with_notebook_counts,
    reorder_zone_notebooks,
    replace_notebook_content,
    update_zone,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Usage visibility ────────────────────────────────────────────────


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD using the configured provider's pricing."""
    provider = settings.llm_provider.lower()
    pricing = LLM_PRICING.get(provider, LLM_PRICING.get("anthropic", {}))
    input_cost = (input_tokens / 1_000_000) * pricing.get("input_per_mtok", 0)
    output_cost = (output_tokens / 1_000_000) * pricing.get("output_per_mtok", 0)
    return round(input_cost + output_cost, 4)


async def _aggregate_usage(db: AsyncSession, start_date: date) -> dict:
    """Sum token usage from start_date to today."""
    result = await db.execute(
        select(
            func.coalesce(func.sum(DailyTokenUsage.input_tokens_used), 0),
            func.coalesce(func.sum(DailyTokenUsage.output_tokens_used), 0),
        ).where(DailyTokenUsage.date >= start_date)
    )
    row = result.one()
    input_tokens = int(row[0])
    output_tokens = int(row[1])
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": _estimate_cost(input_tokens, output_tokens),
    }


@router.get("/usage")
async def get_admin_usage(
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return aggregated token usage and estimated cost for today, this week, and this month."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    return {
        "today": await _aggregate_usage(db, today),
        "this_week": await _aggregate_usage(db, week_start),
        "this_month": await _aggregate_usage(db, month_start),
    }


# ── Audit log ───────────────────────────────────────────────────────


@router.get("/audit-log")
async def get_audit_log(
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
):
    """Return a paginated list of admin audit log entries."""
    return await audit_service.get_audit_log(db, page, per_page)


# ── Zone management ─────────────────────────────────────────────────


@router.get("/zones", response_model=list[ZoneOut])
async def list_admin_zones(
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zones_with_counts = await list_zones_with_notebook_counts(db)
    return [
        ZoneOut(
            id=zone.id,
            title=zone.title,
            description=zone.description,
            order=zone.order,
            created_at=zone.created_at,
            notebook_count=count,
        )
        for zone, count in zones_with_counts
    ]


@router.post("/zones", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
async def create_admin_zone(
    payload: ZoneCreate,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await create_zone(db, payload.title, payload.description)
    await audit_service.log_action(
        db, admin.email, "create", "zone",
        resource_id=zone.id, resource_title=zone.title,
    )
    await db.commit()
    await db.refresh(zone)
    return ZoneOut(
        id=zone.id,
        title=zone.title,
        description=zone.description,
        order=zone.order,
        created_at=zone.created_at,
        notebook_count=0,
    )


@router.put("/zones/{zone_id}", response_model=ZoneOut)
async def update_admin_zone(
    zone_id: uuid.UUID,
    payload: ZoneUpdate,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await update_zone(db, zone_id, **payload.model_dump(exclude_none=True))
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")

    notebook_count = len(await list_zone_notebooks(db, zone_id))
    await audit_service.log_action(
        db, admin.email, "update", "zone",
        resource_id=zone.id, resource_title=zone.title,
    )
    await db.commit()
    await db.refresh(zone)
    return ZoneOut(
        id=zone.id,
        title=zone.title,
        description=zone.description,
        order=zone.order,
        created_at=zone.created_at,
        notebook_count=notebook_count,
    )


@router.delete("/zones/{zone_id}")
async def delete_admin_zone(
    zone_id: uuid.UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_zone(db, zone_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")
    await audit_service.log_action(
        db, admin.email, "delete", "zone", resource_id=zone_id,
    )
    await db.commit()
    return {"message": "Zone deleted"}


@router.post(
    "/zones/{zone_id}/notebooks",
    response_model=ZoneNotebookOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_zone_notebook(
    zone_id: uuid.UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    title: str = Form(...),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
):
    try:
        notebook = await add_notebook(db, zone_id, title, description, file)
    except ZoneValidationError as exc:
        detail = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)

    await audit_service.log_action(
        db, admin.email, "create", "zone_notebook",
        resource_id=notebook.id, resource_title=notebook.title,
    )
    await db.commit()
    await db.refresh(notebook)
    return notebook


@router.get("/zones/{zone_id}/notebooks", response_model=list[ZoneNotebookOut])
async def get_zone_notebooks_for_admin(
    zone_id: uuid.UUID,
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    notebooks = await list_zone_notebooks(db, zone_id)
    return notebooks


@router.put("/notebooks/{notebook_id}", response_model=ZoneNotebookOut)
async def replace_zone_notebook(
    notebook_id: uuid.UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    try:
        notebook = await replace_notebook_content(db, notebook_id, file)
    except ZoneValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    await audit_service.log_action(
        db, admin.email, "update", "zone_notebook",
        resource_id=notebook.id, resource_title=notebook.title,
    )
    await db.commit()
    await db.refresh(notebook)
    return notebook


@router.delete("/notebooks/{notebook_id}")
async def remove_zone_notebook(
    notebook_id: uuid.UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_zone_notebook(db, notebook_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")
    await audit_service.log_action(
        db, admin.email, "delete", "zone_notebook", resource_id=notebook_id,
    )
    await db.commit()
    return {"message": "Notebook deleted"}


@router.put("/zones/{zone_id}/notebooks/reorder")
async def reorder_admin_zone_notebooks(
    zone_id: uuid.UUID,
    payload: ZoneReorder,
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await reorder_zone_notebooks(db, zone_id, payload.notebook_ids)
    except ZoneValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    return {"message": "Notebook order updated"}

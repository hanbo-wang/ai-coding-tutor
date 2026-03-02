"""Admin router: zone management, usage visibility, and audit log."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm_factory import get_llm_provider
from app.ai.model_registry import normalise_llm_provider, validate_supported_llm_model
from app.ai.pricing import estimate_llm_cost_usd
from app.ai.pricing import get_model_pricing
from app.config import LLM_PRICING, settings
from app.dependencies import get_admin_user, get_db
from app.models.chat import ChatMessage, DailyTokenUsage
from app.models.user import User
from app.routers.health import ai_model_catalog_health_check, invalidate_ai_model_catalog_cache
from app.schemas.zone import (
    ZoneCreate,
    ZoneImportResult,
    ZoneNotebookOut,
    ZoneNotebookMetadataUpdate,
    ZoneOut,
    ZoneReorder,
    ZoneSharedFileOut,
    ZoneUpdate,
)
from app.services import audit_service
from app.services.auth_service import verify_password
from app.services.zone_service import (
    ZoneValidationError,
    add_notebook,
    create_zone,
    delete_zone,
    delete_zone_notebook,
    delete_zone_shared_file,
    get_zone,
    get_zone_notebook_for_context,
    import_zone_assets,
    list_zone_notebooks,
    list_zone_shared_files,
    list_zones_with_notebook_counts,
    reorder_zone_notebooks,
    replace_notebook_content,
    update_zone_notebook_metadata,
    update_zone,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
GOOGLE_AI_STUDIO_PROVIDER = "google-aistudio"
GOOGLE_VERTEX_PROVIDER = "google-vertex"


class LLMModelOptionOut(BaseModel):
    provider: str
    provider_label: str
    model: str
    input_per_mtok: float
    output_per_mtok: float


class CurrentLLMOut(BaseModel):
    provider: str
    model: str
    google_gemini_transport: str | None = None


class LLMModelCatalogOut(BaseModel):
    current: CurrentLLMOut
    available_models: list[LLMModelOptionOut]
    checked_at: str
    cached: bool


class LLMModelSwitchIn(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=100)
    admin_password: str = Field(min_length=1, max_length=255)


def _active_google_admin_provider() -> str:
    return (
        GOOGLE_AI_STUDIO_PROVIDER
        if str(settings.google_gemini_transport).strip().lower() == "aistudio"
        else GOOGLE_VERTEX_PROVIDER
    )


def _active_admin_provider() -> str:
    if normalise_llm_provider(settings.llm_provider) == "google":
        return _active_google_admin_provider()
    return normalise_llm_provider(settings.llm_provider)


def _normalise_admin_provider(value: str) -> str:
    provider = str(value or "").strip().lower().replace("_", "-")
    if provider in {"anthropic", "claude"}:
        return "anthropic"
    if provider in {"openai"}:
        return "openai"
    if provider in {"google", "gemini"}:
        return _active_google_admin_provider()
    if provider in {
        "google-aistudio",
        "google-ai-studio",
        "aistudio",
        "ai-studio",
        "studio",
    }:
        return GOOGLE_AI_STUDIO_PROVIDER
    if provider in {
        "google-vertex",
        "google-vertex-ai",
        "vertex",
        "vertex-ai",
        "vertexai",
    }:
        return GOOGLE_VERTEX_PROVIDER
    return normalise_llm_provider(provider)


def _canonical_provider(provider_id: str) -> str:
    if provider_id in {GOOGLE_AI_STUDIO_PROVIDER, GOOGLE_VERTEX_PROVIDER}:
        return "google"
    return normalise_llm_provider(provider_id)


def _google_transport_for_provider(provider_id: str) -> str | None:
    if provider_id == GOOGLE_AI_STUDIO_PROVIDER:
        return "aistudio"
    if provider_id == GOOGLE_VERTEX_PROVIDER:
        return "vertex"
    return None


def _provider_label(provider_id: str) -> str:
    labels = {
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        GOOGLE_AI_STUDIO_PROVIDER: "Google AI Studio",
        GOOGLE_VERTEX_PROVIDER: "Google Cloud Vertex AI",
    }
    return labels.get(provider_id, provider_id)


# ── Usage visibility ────────────────────────────────────────────────


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD using the active provider's pricing."""
    provider = settings.llm_provider.lower()
    default_model_by_provider = {
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
        "google": settings.llm_model_google,
    }
    model_id = default_model_by_provider.get(provider, "")
    if model_id:
        return estimate_llm_cost_usd(provider, model_id, input_tokens, output_tokens)

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

    start_dt = datetime.combine(start_date, time.min)
    cost_result = await db.execute(
        select(
            func.coalesce(func.sum(ChatMessage.estimated_cost_usd), 0.0),
            func.count(ChatMessage.id),
            func.count(ChatMessage.estimated_cost_usd),
        ).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= start_dt,
        )
    )
    cost_row = cost_result.one()
    estimated_cost_usd = round(float(cost_row[0] or 0.0), 4)
    assistant_count = int(cost_row[1] or 0)
    cost_count = int(cost_row[2] or 0)
    coverage = 1.0 if assistant_count == 0 else round(cost_count / assistant_count, 4)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "estimated_cost_coverage": coverage,
    }


def _configured_llm_models_by_provider() -> dict[str, str]:
    return {
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
        GOOGLE_AI_STUDIO_PROVIDER: settings.llm_model_google,
        GOOGLE_VERTEX_PROVIDER: settings.llm_model_google,
    }


def _configured_llm_model(provider_id: str) -> str:
    return _configured_llm_models_by_provider().get(provider_id, "")


def _build_model_option(provider_id: str, model_id: str) -> dict[str, str | float]:
    pricing = get_model_pricing(_canonical_provider(provider_id), model_id)
    return {
        "provider": provider_id,
        "provider_label": _provider_label(provider_id),
        "model": model_id,
        "input_per_mtok": float(pricing.get("input_per_mtok", 0.0)),
        "output_per_mtok": float(pricing.get("output_per_mtok", 0.0)),
    }


def _set_active_llm(provider_id: str, model_id: str) -> None:
    """Update in-memory runtime LLM selection immediately."""
    canonical_provider = _canonical_provider(provider_id)
    settings.llm_provider = canonical_provider
    if canonical_provider == "anthropic":
        settings.llm_model_anthropic = model_id
    elif canonical_provider == "openai":
        settings.llm_model_openai = model_id
    elif canonical_provider == "google":
        settings.llm_model_google = model_id
        transport = _google_transport_for_provider(provider_id)
        if transport:
            settings.google_gemini_transport = transport


def _model_available_in_catalog(catalog: dict, provider_id: str, model_id: str) -> bool:
    llm_groups = catalog.get("smoke_tested_models", {}).get("llm", {})
    provider_entry = llm_groups.get(provider_id, {})
    if not provider_entry and _canonical_provider(provider_id) == "google":
        provider_entry = llm_groups.get("google", {})
    available = provider_entry.get("available_models", [])
    if not isinstance(available, list):
        return False
    return model_id in {str(item) for item in available}


async def _aggregate_usage_for_model(
    db: AsyncSession,
    start_date: date,
    selected_provider_id: str,
    canonical_provider_id: str,
    model_id: str,
) -> dict:
    """Aggregate usage scoped to a specific provider/model pair."""
    provider_filter = ChatMessage.llm_provider == canonical_provider_id
    if selected_provider_id in {GOOGLE_AI_STUDIO_PROVIDER, GOOGLE_VERTEX_PROVIDER}:
        # Include legacy rows stored as plain `google` before provider split.
        provider_filter = or_(
            ChatMessage.llm_provider == selected_provider_id,
            ChatMessage.llm_provider == canonical_provider_id,
        )

    start_dt = datetime.combine(start_date, time.min)
    result = await db.execute(
        select(
            func.coalesce(func.sum(ChatMessage.input_tokens), 0),
            func.coalesce(func.sum(ChatMessage.output_tokens), 0),
            func.coalesce(func.sum(ChatMessage.estimated_cost_usd), 0.0),
            func.count(ChatMessage.id),
            func.count(ChatMessage.estimated_cost_usd),
        ).where(
            ChatMessage.role == "assistant",
            ChatMessage.created_at >= start_dt,
            provider_filter,
            ChatMessage.llm_model == model_id,
        )
    )
    row = result.one()
    input_tokens = int(row[0] or 0)
    output_tokens = int(row[1] or 0)
    estimated_cost_usd = round(float(row[2] or 0.0), 4)
    assistant_count = int(row[3] or 0)
    cost_count = int(row[4] or 0)
    coverage = 1.0 if assistant_count == 0 else round(cost_count / assistant_count, 4)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "estimated_cost_coverage": coverage,
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


@router.get("/usage/by-model")
async def get_admin_usage_by_model(
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: str = Query(..., min_length=1),
    model: str = Query(..., min_length=1),
):
    """Return aggregated usage for one selected provider/model."""
    selected_provider = _normalise_admin_provider(provider)
    canonical_provider = _canonical_provider(selected_provider)
    try:
        canonical_model = validate_supported_llm_model(canonical_provider, model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return {
        "provider": selected_provider,
        "model": canonical_model,
        "today": await _aggregate_usage_for_model(
            db,
            today,
            selected_provider,
            canonical_provider,
            canonical_model,
        ),
        "this_week": await _aggregate_usage_for_model(
            db,
            week_start,
            selected_provider,
            canonical_provider,
            canonical_model,
        ),
        "this_month": await _aggregate_usage_for_model(
            db,
            month_start,
            selected_provider,
            canonical_provider,
            canonical_model,
        ),
    }


@router.get("/llm/models", response_model=LLMModelCatalogOut)
async def get_admin_llm_models(
    _: Annotated[User, Depends(get_admin_user)],
):
    """Return current active LLM and all smoke-tested available switch options."""
    catalog = await ai_model_catalog_health_check(force=False)
    llm_groups = catalog.get("smoke_tested_models", {}).get("llm", {})
    options: list[dict[str, str | float]] = []
    seen: set[tuple[str, str]] = set()

    for provider_id, details in llm_groups.items():
        admin_provider = _normalise_admin_provider(str(provider_id))
        canonical_provider = _canonical_provider(admin_provider)
        models = details.get("available_models", [])
        if not isinstance(models, list):
            continue
        for model_id in models:
            try:
                canonical_model = validate_supported_llm_model(
                    canonical_provider, str(model_id)
                )
            except ValueError:
                continue
            key = (admin_provider, canonical_model)
            if key in seen:
                continue
            seen.add(key)
            options.append(_build_model_option(admin_provider, canonical_model))

    current_provider = _active_admin_provider()
    current_model = _configured_llm_model(current_provider)
    if current_model:
        key = (current_provider, current_model)
        if key not in seen:
            options.append(_build_model_option(current_provider, current_model))

    options.sort(key=lambda item: (str(item["provider_label"]), str(item["model"])))
    current = {
        "provider": current_provider,
        "model": current_model,
        "google_gemini_transport": (
            settings.google_gemini_transport
            if current_provider in {GOOGLE_AI_STUDIO_PROVIDER, GOOGLE_VERTEX_PROVIDER}
            else None
        ),
    }
    return {
        "current": current,
        "available_models": options,
        "checked_at": str(catalog.get("checked_at", "")),
        "cached": bool(catalog.get("cached", False)),
    }


@router.post("/llm/switch")
async def switch_admin_llm_model(
    payload: LLMModelSwitchIn,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Switch the runtime LLM immediately after admin password confirmation."""
    if not verify_password(payload.admin_password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin password is incorrect.",
        )

    target_provider = _normalise_admin_provider(payload.provider)
    canonical_target_provider = _canonical_provider(target_provider)
    try:
        target_model = validate_supported_llm_model(canonical_target_provider, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    catalog = await ai_model_catalog_health_check(force=False)
    if not _model_available_in_catalog(catalog, target_provider, target_model):
        catalog = await ai_model_catalog_health_check(force=True)
        if not _model_available_in_catalog(catalog, target_provider, target_model):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected model is not currently available for switching.",
            )

    previous_provider = _active_admin_provider()
    previous_models = _configured_llm_models_by_provider()
    previous_transport = settings.google_gemini_transport
    previous_model = previous_models.get(previous_provider, "")
    _set_active_llm(target_provider, target_model)

    try:
        resolved = get_llm_provider(settings)
        if resolved.provider_id != canonical_target_provider or resolved.model_id != target_model:
            raise RuntimeError(
                "The selected model could not be activated because the runtime fell back."
            )
        target_transport = _google_transport_for_provider(target_provider)
        if target_transport and settings.google_gemini_transport != target_transport:
            raise RuntimeError("The selected Google transport could not be activated.")
    except Exception as exc:
        settings.llm_provider = _canonical_provider(previous_provider)
        settings.llm_model_anthropic = previous_models["anthropic"]
        settings.llm_model_openai = previous_models["openai"]
        settings.llm_model_google = previous_models[GOOGLE_VERTEX_PROVIDER]
        settings.google_gemini_transport = previous_transport
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to switch LLM model: {exc}",
        )

    invalidate_ai_model_catalog_cache()

    await audit_service.log_action(
        db,
        admin.email,
        "update",
        "llm_model",
        details=(
            "switched active LLM "
            f"from {previous_provider}/{previous_model} to {target_provider}/{target_model}"
        ),
    )
    await db.commit()

    pricing = get_model_pricing(canonical_target_provider, target_model)
    return {
        "message": "LLM switched successfully.",
        "current": {
            "provider": target_provider,
            "model": target_model,
            "google_gemini_transport": (
                settings.google_gemini_transport
                if target_provider in {GOOGLE_AI_STUDIO_PROVIDER, GOOGLE_VERTEX_PROVIDER}
                else None
            ),
        },
        "pricing": {
            "input_per_mtok": float(pricing.get("input_per_mtok", 0.0)),
            "output_per_mtok": float(pricing.get("output_per_mtok", 0.0)),
        },
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
    existing_zone = await get_zone(db, zone_id)
    if existing_zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")
    old_title = existing_zone.title
    old_description = existing_zone.description

    fields = payload.model_dump(exclude_unset=True)
    zone = await update_zone(db, zone_id, **fields)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")

    notebook_count = len(await list_zone_notebooks(db, zone_id))
    detail_parts: list[str] = []
    if old_title != zone.title:
        detail_parts.append(f"title: '{old_title}' -> '{zone.title}'")
    if old_description != zone.description:
        detail_parts.append("description updated")
    await audit_service.log_action(
        db, admin.email, "update", "zone",
        resource_id=zone.id, resource_title=zone.title,
        details="; ".join(detail_parts) if detail_parts else None,
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


@router.post(
    "/zones/{zone_id}/assets",
    response_model=ZoneImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_zone_assets_bundle(
    zone_id: uuid.UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    relative_paths: list[str] | None = Form(default=None),
):
    try:
        result = await import_zone_assets(db, zone_id, files, relative_paths or [])
    except ZoneValidationError as exc:
        detail = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)

    detail = (
        f"imported notebooks={result['notebooks_created']}, "
        f"shared_created={result['shared_files_created']}, "
        f"shared_updated={result['shared_files_updated']}"
    )
    await audit_service.log_action(
        db,
        admin.email,
        "update",
        "zone_assets",
        resource_id=zone_id,
        details=detail,
    )
    await db.commit()
    return ZoneImportResult(**result)


@router.get("/zones/{zone_id}/notebooks", response_model=list[ZoneNotebookOut])
async def get_zone_notebooks_for_admin(
    zone_id: uuid.UUID,
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    notebooks = await list_zone_notebooks(db, zone_id)
    return notebooks


@router.get("/zones/{zone_id}/shared-files", response_model=list[ZoneSharedFileOut])
async def get_zone_shared_files_for_admin(
    zone_id: uuid.UUID,
    _: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zone not found")
    return await list_zone_shared_files(db, zone_id)


@router.patch("/notebooks/{notebook_id}/metadata", response_model=ZoneNotebookOut)
async def update_zone_notebook_metadata_for_admin(
    notebook_id: uuid.UUID,
    payload: ZoneNotebookMetadataUpdate,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No metadata fields provided.",
        )

    existing = await get_zone_notebook_for_context(db, notebook_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    old_title = existing.title
    old_description = existing.description
    try:
        notebook = await update_zone_notebook_metadata(
            db,
            notebook_id,
            title=fields.get("title"),
            description=fields.get("description"),
            description_provided="description" in fields,
        )
    except ZoneValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if notebook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found")

    detail_parts: list[str] = []
    if old_title != notebook.title:
        detail_parts.append(f"title: '{old_title}' -> '{notebook.title}'")
    if old_description != notebook.description:
        detail_parts.append("description updated")
    await audit_service.log_action(
        db,
        admin.email,
        "update",
        "zone_notebook",
        resource_id=notebook.id,
        resource_title=notebook.title,
        details="; ".join(detail_parts) if detail_parts else None,
    )
    await db.commit()
    await db.refresh(notebook)
    return notebook


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


@router.delete("/shared-files/{shared_file_id}")
async def remove_zone_shared_file(
    shared_file_id: uuid.UUID,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_zone_shared_file(db, shared_file_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared file not found")
    await audit_service.log_action(
        db,
        admin.email,
        "delete",
        "zone_shared_file",
        resource_id=shared_file_id,
    )
    await db.commit()
    return {"message": "Shared file deleted"}


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


# ── LLM error visibility ───────────────────────────────────────────


@router.get("/llm-errors")
async def get_llm_errors(
    _: Annotated[User, Depends(get_admin_user)],
):
    """Return recent LLM errors from the in-memory ring buffer, newest first."""
    from app.routers.chat import get_recent_llm_errors

    return {"errors": get_recent_llm_errors()}


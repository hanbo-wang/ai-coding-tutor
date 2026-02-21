"""Record and retrieve admin audit log entries."""

import uuid
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AdminAuditLog


async def log_action(
    db: AsyncSession,
    admin_email: str,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    resource_title: str | None = None,
    details: str | None = None,
) -> AdminAuditLog:
    """Create an audit log entry for an admin action."""
    entry = AdminAuditLog(
        admin_email=admin_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_title=resource_title,
        details=details,
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_audit_log(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Return a paginated list of audit entries in reverse chronological order."""
    count_result = await db.execute(select(func.count(AdminAuditLog.id)))
    total = count_result.scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        select(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    entries = result.scalars().all()

    return {
        "entries": [
            {
                "id": str(entry.id),
                "admin_email": entry.admin_email,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": str(entry.resource_id) if entry.resource_id else None,
                "resource_title": entry.resource_title,
                "details": entry.details,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in entries
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": ceil(total / per_page) if per_page > 0 else 0,
    }

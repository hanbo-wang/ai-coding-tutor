"""Admin audit service unit tests."""

from datetime import datetime, timezone
import uuid

import pytest

from app.models.audit import AdminAuditLog
from app.services import audit_service


class _FakeCountResult:
    def __init__(self, total: int) -> None:
        self._total = total

    def scalar(self) -> int:
        return self._total


class _FakeEntriesScalars:
    def __init__(self, entries: list[AdminAuditLog]) -> None:
        self._entries = entries

    def all(self) -> list[AdminAuditLog]:
        return self._entries


class _FakeEntriesResult:
    def __init__(self, entries: list[AdminAuditLog]) -> None:
        self._entries = entries

    def scalars(self) -> _FakeEntriesScalars:
        return _FakeEntriesScalars(self._entries)


class _FakeReadSession:
    def __init__(self, total: int, entries: list[AdminAuditLog]) -> None:
        self._responses = [_FakeCountResult(total), _FakeEntriesResult(entries)]

    async def execute(self, _statement):
        return self._responses.pop(0)


class _FakeWriteSession:
    def __init__(self) -> None:
        self.added: list[AdminAuditLog] = []
        self.flushed = False

    def add(self, entry: AdminAuditLog) -> None:
        self.added.append(entry)

    async def flush(self) -> None:
        self.flushed = True


def test_audit_log_model_fields() -> None:
    """AdminAuditLog should store all required fields."""
    entry = AdminAuditLog(
        admin_email="admin@example.com",
        action="create",
        resource_type="zone",
        resource_id=uuid.uuid4(),
        resource_title="Linear Algebra Basics",
        details="Created new zone.",
    )
    assert entry.admin_email == "admin@example.com"
    assert entry.action == "create"
    assert entry.resource_type == "zone"
    assert entry.resource_title == "Linear Algebra Basics"


def test_audit_log_model_optional_fields() -> None:
    """AdminAuditLog should accept None for optional fields."""
    entry = AdminAuditLog(
        admin_email="admin@example.com",
        action="delete",
        resource_type="zone_notebook",
        resource_id=None,
        resource_title=None,
        details=None,
    )
    assert entry.resource_id is None
    assert entry.resource_title is None
    assert entry.details is None


def test_audit_log_action_values() -> None:
    """Verify the three expected action values can be stored."""
    for action in ("create", "update", "delete"):
        entry = AdminAuditLog(
            admin_email="admin@example.com",
            action=action,
            resource_type="zone",
        )
        assert entry.action == action


@pytest.mark.asyncio
async def test_log_action_adds_entry_and_flushes() -> None:
    """log_action should stage the entry and flush once."""
    db = _FakeWriteSession()

    entry = await audit_service.log_action(
        db,
        admin_email="admin@example.com",
        action="update",
        resource_type="zone",
        resource_title="Week 1",
    )

    assert db.flushed is True
    assert db.added == [entry]
    assert entry.admin_email == "admin@example.com"
    assert entry.resource_title == "Week 1"


@pytest.mark.asyncio
async def test_get_audit_log_returns_paginated_shape() -> None:
    """get_audit_log should return entries, paging fields, and totals."""
    entry = AdminAuditLog(
        admin_email="admin@example.com",
        action="create",
        resource_type="zone",
        resource_id=uuid.uuid4(),
        resource_title="Week 2",
        details="Created zone",
    )
    entry.created_at = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)

    db = _FakeReadSession(total=3, entries=[entry])

    payload = await audit_service.get_audit_log(db, page=2, per_page=2)

    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["per_page"] == 2
    assert payload["total_pages"] == 2
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["admin_email"] == "admin@example.com"
    assert payload["entries"][0]["resource_title"] == "Week 2"

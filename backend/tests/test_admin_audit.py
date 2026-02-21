"""Admin audit service unit tests."""

import uuid

from app.models.audit import AdminAuditLog


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

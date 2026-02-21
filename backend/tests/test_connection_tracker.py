"""Connection tracker unit tests."""

from app.services.connection_tracker import ConnectionTracker


def test_add_and_remove(monkeypatch) -> None:
    """Adding and removing connections should update counts correctly."""
    monkeypatch.setattr("app.services.connection_tracker.settings.max_ws_connections_per_user", 3)
    tracker = ConnectionTracker()
    tracker.add("user-1", "conn-a")
    tracker.add("user-1", "conn-b")
    assert tracker.can_connect("user-1")
    tracker.remove("user-1", "conn-a")
    tracker.remove("user-1", "conn-b")
    assert tracker.can_connect("user-1")


def test_limit_enforcement(monkeypatch) -> None:
    """The 4th connection for the same user should be rejected."""
    monkeypatch.setattr("app.services.connection_tracker.settings.max_ws_connections_per_user", 3)
    tracker = ConnectionTracker()
    tracker.add("user-1", "conn-a")
    tracker.add("user-1", "conn-b")
    tracker.add("user-1", "conn-c")
    assert not tracker.can_connect("user-1")


def test_multi_user_isolation(monkeypatch) -> None:
    """Different users should have independent connection pools."""
    monkeypatch.setattr("app.services.connection_tracker.settings.max_ws_connections_per_user", 2)
    tracker = ConnectionTracker()
    tracker.add("user-1", "conn-a")
    tracker.add("user-1", "conn-b")
    assert not tracker.can_connect("user-1")
    assert tracker.can_connect("user-2")

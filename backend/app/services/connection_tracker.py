"""Track active WebSocket connections per user."""

from app.config import settings


class ConnectionTracker:
    """Enforce concurrent WebSocket connection limits per user."""

    def __init__(self) -> None:
        self._connections: dict[str, set[str]] = {}

    def can_connect(self, user_id: str) -> bool:
        """Return True if the user has fewer than the maximum allowed connections."""
        active = self._connections.get(user_id)
        if active is None:
            return True
        return len(active) < settings.max_ws_connections_per_user

    def add(self, user_id: str, connection_id: str) -> None:
        """Register a new connection."""
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(connection_id)

    def remove(self, user_id: str, connection_id: str) -> None:
        """Unregister a connection on disconnect."""
        active = self._connections.get(user_id)
        if active is not None:
            active.discard(connection_id)
            if not active:
                del self._connections[user_id]


# Single instance shared across the application.
connection_tracker = ConnectionTracker()

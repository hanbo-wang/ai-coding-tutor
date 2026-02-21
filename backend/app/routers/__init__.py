from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.routers.upload import router as upload_router
from app.routers.notebooks import router as notebooks_router
from app.routers.zones import router as zones_router
from app.routers.admin import router as admin_router

__all__ = [
    "auth_router",
    "chat_router",
    "health_router",
    "upload_router",
    "notebooks_router",
    "zones_router",
    "admin_router",
]

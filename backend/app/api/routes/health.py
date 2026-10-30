from fastapi import APIRouter

from app.config import get_settings
from app.database.database import get_connection

router = APIRouter()


@router.get("/health")
def health():
    settings = get_settings()
    db_ok = True
    try:
        get_connection().execute("SELECT 1")
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "paypal_configured": bool(settings.paypal_client_id and settings.paypal_client_secret),
        "groq_configured": bool(settings.groq_api_key),
        "paypal_environment": settings.paypal_environment,
        "model": settings.groq_model,
    }

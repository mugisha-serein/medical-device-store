from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


@router.post("/send-test")
async def send_test_notification(
    admin: User = Depends(require_admin),
):
    """Send a test notification (admin only)."""
    from app.notifications.tasks import send_order_confirmation
    # In a real implementation, this would be triggered by the outbox processor
    return {"message": "Test notification queued."}

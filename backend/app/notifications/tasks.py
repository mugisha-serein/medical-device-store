"""
Celery tasks for async notifications.
Triggered off the orders outbox events.
"""

from celery import Celery
import httpx

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "activelifemedical",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send email via Resend API."""
    if not settings.RESEND_API_KEY:
        print(f"[DEV] Email to {to}: {subject}")
        return True

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
                timeout=30.0,
            )
            return response.status_code == 200
        except Exception:
            return False


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_confirmation(self, order_id: str, user_email: str, total: float):
    """Send order confirmation email."""
    html = f"""
    <h2>Order Confirmed</h2>
    <p>Thank you for your order!</p>
    <p><strong>Order ID:</strong> {order_id}</p>
    <p><strong>Total:</strong> ${total:.2f}</p>
    <p>We'll notify you when your order is processed.</p>
    """
    try:
        import asyncio
        asyncio.run(send_email(user_email, f"Order {order_id} Confirmed", html))
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_received(self, order_id: str, user_email: str, total: float):
    """Send payment received email."""
    html = f"""
    <h2>Payment Received</h2>
    <p>We've received your payment for order {order_id}.</p>
    <p><strong>Amount:</strong> ${total:.2f}</p>
    <p>Your order is now being processed.</p>
    """
    try:
        import asyncio
        asyncio.run(send_email(user_email, f"Payment Received - Order {order_id}", html))
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_shipped(self, order_id: str, user_email: str):
    """Send order shipped email."""
    html = f"""
    <h2>Order Shipped</h2>
    <p>Your order {order_id} has been shipped!</p>
    <p>You'll receive tracking information shortly.</p>
    """
    try:
        import asyncio
        asyncio.run(send_email(user_email, f"Order {order_id} Shipped", html))
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_cancelled(self, order_id: str, user_email: str):
    """Send order cancelled email."""
    html = f"""
    <h2>Order Cancelled</h2>
    <p>Your order {order_id} has been cancelled.</p>
    <p>If you paid, a refund will be processed shortly.</p>
    """
    try:
        import asyncio
        asyncio.run(send_email(user_email, f"Order {order_id} Cancelled", html))
    except Exception as exc:
        self.retry(exc=exc)


@celery_app.task
def process_outbox_events():
    """
    Periodic task to process outbox events and trigger notifications.
    In production, this would poll the outbox table.
    """
    # This is a simplified version. In a full implementation, you'd:
    # 1. Query unprocessed OutboxEvent records
    # 2. Dispatch the appropriate Celery task based on event_type
    # 3. Mark events as processed
    pass


# Auto-discover tasks
celery_app.autodiscover_tasks(["app.notifications"])

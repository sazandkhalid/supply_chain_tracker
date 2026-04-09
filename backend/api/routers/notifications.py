"""
WhatsApp notification subscription management.

Endpoints
---------
POST   /api/v1/notifications/whatsapp          — subscribe a number
GET    /api/v1/notifications/whatsapp          — list active subscribers for this org
DELETE /api/v1/notifications/whatsapp/{sub_id} — remove a subscriber
POST   /api/v1/notifications/whatsapp/test     — send a test message to all subscribers
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.api.dependencies import CurrentUser, DbSession
from backend.models.notification_subscription import NotificationSubscription
from backend.schemas.notification import (
    SubscribeRequest,
    SubscriptionResponse,
    TestNotificationResponse,
)
from backend.services.whatsapp_notifier import notifier

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post(
    "/whatsapp",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe a WhatsApp number to receive alerts",
)
async def subscribe(
    body: SubscribeRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    """
    Register a WhatsApp number to receive shipment exception alerts for this
    organisation.  Duplicate numbers within the same org are rejected.
    """
    existing = await db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.org_id == current_user.org_id,
            NotificationSubscription.phone_number == body.phone_number,
            NotificationSubscription.active.is_(True),
        )
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.phone_number} is already subscribed for this organisation.",
        )

    sub = NotificationSubscription(
        org_id=current_user.org_id,
        created_by=current_user.user_id,
        phone_number=body.phone_number,
        label=body.label,
        notify_critical=body.notify_critical,
        notify_high=body.notify_high,
        notify_expiry=body.notify_expiry,
    )
    db.add(sub)
    await db.flush()
    return sub


@router.get(
    "/whatsapp",
    response_model=list[SubscriptionResponse],
    summary="List active WhatsApp subscribers for this org",
)
async def list_subscriptions(db: DbSession, current_user: CurrentUser):
    subs = (
        await db.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.org_id == current_user.org_id,
                NotificationSubscription.active.is_(True),
            )
        )
    ).scalars().all()
    return subs


@router.delete(
    "/whatsapp/{sub_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a WhatsApp subscriber",
)
async def unsubscribe(sub_id: UUID, db: DbSession, current_user: CurrentUser):
    sub = await db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.id == sub_id,
            NotificationSubscription.org_id == current_user.org_id,
        )
    )
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found.")
    sub.active = False


@router.post(
    "/whatsapp/test",
    response_model=TestNotificationResponse,
    summary="Send a test WhatsApp message to all active subscribers",
)
async def send_test_message(db: DbSession, current_user: CurrentUser):
    """
    Useful for verifying Twilio credentials and that team members have accepted
    the WhatsApp opt-in before real alerts start firing.
    """
    if not notifier.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "WhatsApp notifications are not configured on this server. "
                "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM."
            ),
        )

    subs = (
        await db.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.org_id == current_user.org_id,
                NotificationSubscription.active.is_(True),
            )
        )
    ).scalars().all()

    if not subs:
        return TestNotificationResponse(sent=0, total_subscribers=0, detail="No active subscribers.")

    numbers = [s.phone_number for s in subs]
    sent = notifier.send_raw(
        numbers,
        (
            "✅ TradeFlow AI — Test Notification\n"
            "اختبار الإشعارات — تريدفلو\n\n"
            "Your WhatsApp alerts are configured and working.\n"
            "إشعارات واتساب تعمل بنجاح."
        ),
    )

    return TestNotificationResponse(sent=sent, total_subscribers=len(numbers))

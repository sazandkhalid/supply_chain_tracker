# Import all models so Alembic can discover them
from backend.models.organization import Organization
from backend.models.user import User
from backend.models.shipment import Shipment
from backend.models.document import Document
from backend.models.exception_event import ExceptionEvent
from backend.models.shipment_event import ShipmentEvent
from backend.models.notification_subscription import NotificationSubscription

__all__ = [
    "Organization",
    "User",
    "Shipment",
    "Document",
    "ExceptionEvent",
    "ShipmentEvent",
    "NotificationSubscription",
]

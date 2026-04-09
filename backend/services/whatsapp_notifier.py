"""
WhatsApp notification service via Twilio.

Sends alerts to subscribed team members when critical trade exceptions are
detected or document deadlines approach.  Messages are bilingual
(English + Arabic) to suit Saudi logistics teams.

Usage
-----
The module exposes a lazily-initialised singleton ``notifier``.  Callers
check ``notifier.enabled`` before calling any send method — if Twilio
credentials are absent the class silently no-ops so the rest of the app
keeps running.

    from backend.services.whatsapp_notifier import notifier

    if notifier.enabled:
        notifier.notify_critical_exceptions(numbers, shipment_ref, exceptions)
"""

import logging
from dataclasses import dataclass
from typing import List

from backend.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class _ExceptionSummary:
    """Minimal view of an exception needed to compose a notification."""
    severity: str
    title: str


class WhatsAppNotifier:
    """
    Thin wrapper around the Twilio Messages API for WhatsApp delivery.

    All public methods return the number of messages successfully dispatched
    so callers can log / surface delivery stats without needing to catch
    exceptions themselves.
    """

    def __init__(self) -> None:
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_FROM):
            logger.info(
                "WhatsApp notifications disabled: TWILIO_ACCOUNT_SID, "
                "TWILIO_AUTH_TOKEN, or TWILIO_WHATSAPP_FROM not set."
            )
            self._enabled = False
            return

        try:
            from twilio.rest import Client  # type: ignore[import]
            self._client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            self._from_wa = f"whatsapp:{settings.TWILIO_WHATSAPP_FROM}"
            self._enabled = True
            logger.info("WhatsApp notifier ready (from=%s).", settings.TWILIO_WHATSAPP_FROM)
        except ImportError:
            logger.error("twilio package not installed — run: pip install twilio")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, to_number: str, body: str) -> bool:
        """Dispatch a single WhatsApp message.  Returns True on success."""
        if not self._enabled:
            return False
        try:
            msg = self._client.messages.create(
                from_=self._from_wa,
                to=f"whatsapp:{to_number}",
                body=body,
            )
            logger.info("WhatsApp dispatched sid=%s to=%s", msg.sid, to_number)
            return True
        except Exception as exc:
            logger.error("WhatsApp send failed to=%s: %s", to_number, exc)
            return False

    @staticmethod
    def _severity_emoji(severity: str) -> str:
        return {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "🔶", "LOW": "🔷"}.get(severity.upper(), "ℹ️")

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    def notify_critical_exceptions(
        self,
        recipients: List[str],
        shipment_ref: str,
        exceptions: List[_ExceptionSummary],
    ) -> int:
        """
        Alert team about critical / high exceptions on a shipment.

        Parameters
        ----------
        recipients:   E.164 phone numbers, e.g. ["+966501234567"]
        shipment_ref: Human-readable shipment reference shown in the message.
        exceptions:   List of exception summaries (severity + title).

        Returns the number of messages successfully sent.
        """
        if not exceptions or not recipients:
            return 0

        top = exceptions[0]
        emoji = self._severity_emoji(top.severity)
        count = len(exceptions)
        extra = f" (+{count - 1} more)" if count > 1 else ""

        body = (
            f"{emoji} TradeFlow AI — Shipment Alert\n"
            f"تنبيه شحنة — تريدفلو\n\n"
            f"📦 Shipment: {shipment_ref}\n"
            f"🔍 {top.severity}: {top.title}{extra}\n\n"
            f"افتح التطبيق لمراجعة التفاصيل وحل المشكلة.\n"
            f"Open the app to review and resolve."
        )

        sent = 0
        for number in recipients:
            if self._send(number, body):
                sent += 1
        return sent

    def notify_document_expiry(
        self,
        recipients: List[str],
        shipment_ref: str,
        doc_type: str,
        days_remaining: int,
        expiry_date: str,
    ) -> int:
        """
        Alert team that a document is expiring soon.

        Returns the number of messages successfully sent.
        """
        if not recipients:
            return 0

        friendly_doc = doc_type.replace("_", " ").title()
        body = (
            f"⏰ TradeFlow AI — Document Expiry Warning\n"
            f"تحذير انتهاء صلاحية وثيقة\n\n"
            f"📦 Shipment: {shipment_ref}\n"
            f"📄 Document: {friendly_doc}\n"
            f"📅 Expires: {expiry_date} ({days_remaining} day(s) remaining)\n\n"
            f"جدد الوثيقة قبل التخليص الجمركي.\n"
            f"Renew before customs clearance."
        )

        sent = 0
        for number in recipients:
            if self._send(number, body):
                sent += 1
        return sent

    def send_raw(self, recipients: List[str], body: str) -> int:
        """Send an arbitrary message body to a list of recipients."""
        sent = 0
        for number in recipients:
            if self._send(number, body):
                sent += 1
        return sent


# Module-level singleton — instantiated once at import time.
notifier = WhatsAppNotifier()

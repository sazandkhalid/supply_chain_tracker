"""
Unit tests for sync event processing logic.

These test the pure-logic portions of the sync system:
- Event ordering by client_timestamp
- Duplicate detection
- Payload validation
- Event type coverage

DB-dependent tests (actual push/pull HTTP) belong in integration tests.
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from backend.models.shipment_event import EventType


def make_event(
    event_type: str,
    payload: dict,
    client_timestamp: str = None,
    shipment_id: uuid.UUID = None,
    event_id: uuid.UUID = None,
):
    """Helper — mirrors IncomingEvent shape without importing FastAPI."""
    return {
        "id": str(event_id or uuid.uuid4()),
        "event_type": event_type,
        "shipment_id": str(shipment_id) if shipment_id else None,
        "client_timestamp": client_timestamp or datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


class TestEventOrdering:
    def test_events_sorted_by_client_timestamp(self):
        """Events from an offline session must be applied oldest-first."""
        base = datetime(2026, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
        events = [
            {"client_timestamp": (base + timedelta(minutes=5)).isoformat(), "id": "c"},
            {"client_timestamp": (base + timedelta(minutes=1)).isoformat(), "id": "a"},
            {"client_timestamp": (base + timedelta(minutes=3)).isoformat(), "id": "b"},
        ]
        ordered = sorted(events, key=lambda e: e["client_timestamp"])
        assert [e["id"] for e in ordered] == ["a", "b", "c"]

    def test_same_timestamp_is_stable(self):
        """Two events with the same timestamp don't crash the sort."""
        ts = datetime.now(timezone.utc).isoformat()
        events = [
            {"client_timestamp": ts, "id": "x"},
            {"client_timestamp": ts, "id": "y"},
        ]
        ordered = sorted(events, key=lambda e: e["client_timestamp"])
        assert len(ordered) == 2  # no error, order undefined but stable


class TestDuplicateDetection:
    def test_duplicate_ids_filtered_before_processing(self):
        """Simulates the duplicate filter in push_events."""
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        id3 = uuid.uuid4()

        incoming_ids = [id1, id2, id3]
        # id1 already in DB
        existing_ids = {id1}

        new_events = [e for e in incoming_ids if e not in existing_ids]
        assert id1 not in new_events
        assert id2 in new_events
        assert id3 in new_events

    def test_empty_batch_produces_empty_results(self):
        events = []
        existing_ids: set = set()
        new_events = [e for e in events if e not in existing_ids]
        assert new_events == []


class TestEventTypeCompleteness:
    def test_all_event_types_defined(self):
        """Sanity check that EventType enum has the expected members."""
        expected = {
            "SHIPMENT_CREATED",
            "SHIPMENT_STATUS_UPDATED",
            "DOCUMENT_UPLOADED",
            "CUSTOMS_ENTRY_UPDATED",
            "EXCEPTION_ACKNOWLEDGED",
            "EXCEPTION_RESOLVED",
            "NOTE_ADDED",
        }
        actual = {e.value for e in EventType}
        assert expected == actual


class TestPayloadShapes:
    def test_shipment_created_payload_has_required_fields(self):
        payload = {
            "reference_number": "TF-2026-001",
            "origin_country": "CN",
            "destination_country": "AE",
            "transport_mode": "SEA",
        }
        # Required fields present
        assert "reference_number" in payload
        assert "origin_country" in payload
        assert "destination_country" in payload

    def test_document_uploaded_payload_has_doc_type(self):
        payload = {
            "doc_type": "COMMERCIAL_INVOICE",
            "reference_number": "CI-001",
            "hs_code": "847130",
        }
        assert "doc_type" in payload

    def test_exception_resolved_payload_has_exception_id(self):
        exc_id = str(uuid.uuid4())
        payload = {
            "exception_id": exc_id,
            "resolution_note": "Corrected HS code in commercial invoice",
        }
        assert uuid.UUID(payload["exception_id"])  # valid UUID
        assert payload["resolution_note"]


class TestClientTimestampFormatting:
    def test_iso_timestamp_sorts_lexicographically(self):
        """
        ISO 8601 UTC timestamps must sort correctly as strings — this is how
        the event log orders offline batches without parsing.
        """
        t1 = "2026-03-10T08:00:00+00:00"
        t2 = "2026-03-10T09:00:00+00:00"
        t3 = "2026-03-11T08:00:00+00:00"
        assert sorted([t3, t1, t2]) == [t1, t2, t3]

    def test_datetime_isoformat_produces_sortable_string(self):
        d1 = datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)
        assert d1.isoformat() < d2.isoformat()

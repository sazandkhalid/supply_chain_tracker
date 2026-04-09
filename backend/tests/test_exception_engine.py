"""
Tests for the exception detection engine.

Run with:  pytest backend/tests/test_exception_engine.py -v
"""

from datetime import date, timedelta

import pytest

from backend.models.document import DocumentType
from backend.models.exception_event import ExceptionSeverity, ExceptionType
from backend.services.exception_engine import (
    DocumentSnapshot,
    ExceptionResult,
    ShipmentContext,
    check_certificate_validity,
    check_country_of_origin_consistency,
    check_hs_code_consistency,
    check_invalid_hs_code,
    check_missing_documents,
    check_quantity_discrepancy,
    check_value_discrepancy,
    check_weight_discrepancy,
    run_exception_checks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sea_shipment() -> ShipmentContext:
    return ShipmentContext(
        reference_number="TF-2026-001",
        origin_country="CN",
        destination_country="AE",
        transport_mode="SEA",
        hs_code="847130",
        gross_weight_kg=5000.0,
        quantity=100.0,
        quantity_unit="CTN",
        declared_value=50000.0,
        currency="USD",
    )


@pytest.fixture
def complete_sea_docs() -> list[DocumentSnapshot]:
    """A clean, complete set of sea freight documents — no exceptions expected."""
    today = date.today()
    return [
        DocumentSnapshot(
            doc_type=DocumentType.BILL_OF_LADING,
            reference_number="BL-2026-001",
            gross_weight_kg=5000.0,
        ),
        DocumentSnapshot(
            doc_type=DocumentType.COMMERCIAL_INVOICE,
            reference_number="CI-2026-001",
            hs_code="847130",
            quantity=100.0,
            quantity_unit="CTN",
            declared_value=50000.0,
            currency="USD",
        ),
        DocumentSnapshot(
            doc_type=DocumentType.PACKING_LIST,
            reference_number="PL-2026-001",
            gross_weight_kg=5000.0,
            quantity=100.0,
            quantity_unit="CTN",
        ),
        DocumentSnapshot(
            doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
            reference_number="CO-2026-001",
            issue_date=today - timedelta(days=10),
            expiry_date=today + timedelta(days=80),
            hs_code="847130",
            issuing_country="CN",
        ),
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_no_exceptions_for_clean_shipment(self, sea_shipment, complete_sea_docs):
        results = run_exception_checks(sea_shipment, complete_sea_docs)
        assert results == [], f"Expected no exceptions, got: {[r.exception_type for r in results]}"


# ---------------------------------------------------------------------------
# Rule 1: Missing documents
# ---------------------------------------------------------------------------


class TestMissingDocuments:
    def test_flags_missing_bill_of_lading(self, sea_shipment, complete_sea_docs):
        docs = [d for d in complete_sea_docs if d.doc_type != DocumentType.BILL_OF_LADING]
        results = check_missing_documents(sea_shipment, docs)
        assert any(r.exception_type == ExceptionType.MISSING_REQUIRED_DOC for r in results)
        assert any(DocumentType.BILL_OF_LADING in r.affected_doc_types for r in results)

    def test_flags_missing_certificate_of_origin(self, sea_shipment, complete_sea_docs):
        docs = [d for d in complete_sea_docs if d.doc_type != DocumentType.CERTIFICATE_OF_ORIGIN]
        results = check_missing_documents(sea_shipment, docs)
        types = [r.rule_metadata["required_doc_type"] for r in results]
        assert DocumentType.CERTIFICATE_OF_ORIGIN in types

    def test_flags_multiple_missing_docs(self, sea_shipment):
        # Only packing list provided
        docs = [
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, reference_number="PL-001")
        ]
        results = check_missing_documents(sea_shipment, docs)
        assert len(results) == 3  # BL, CI, CO missing

    def test_no_false_positive_when_complete(self, sea_shipment, complete_sea_docs):
        results = check_missing_documents(sea_shipment, complete_sea_docs)
        assert results == []

    def test_air_shipment_requires_airway_bill_not_bl(self):
        shipment = ShipmentContext(
            reference_number="TF-AIR-001",
            origin_country="CN",
            destination_country="SA",
            transport_mode="AIR",
        )
        docs = [
            DocumentSnapshot(doc_type=DocumentType.AIRWAY_BILL),
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST),
            DocumentSnapshot(doc_type=DocumentType.CERTIFICATE_OF_ORIGIN),
        ]
        results = check_missing_documents(shipment, docs)
        assert results == []

    def test_road_shipment_does_not_require_bl(self):
        shipment = ShipmentContext(
            reference_number="TF-ROAD-001",
            origin_country="TR",
            destination_country="IQ",
            transport_mode="ROAD",
        )
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST),
            DocumentSnapshot(doc_type=DocumentType.CERTIFICATE_OF_ORIGIN),
        ]
        results = check_missing_documents(shipment, docs)
        assert results == []


# ---------------------------------------------------------------------------
# Rule 2: HS code consistency
# ---------------------------------------------------------------------------


class TestHsCodeConsistency:
    def test_flags_mismatch_between_invoice_and_co(self, sea_shipment, complete_sea_docs):
        # Modify CO to use a different HS code
        docs = list(complete_sea_docs)
        docs[-1] = DocumentSnapshot(
            doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
            hs_code="847141",  # Different from shipment (847130)
            issuing_country="CN",
            issue_date=date.today() - timedelta(days=5),
            expiry_date=date.today() + timedelta(days=85),
        )
        results = check_hs_code_consistency(sea_shipment, docs)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.HS_CODE_MISMATCH
        assert results[0].severity == ExceptionSeverity.CRITICAL

    def test_agrees_when_all_hs_codes_match(self, sea_shipment, complete_sea_docs):
        results = check_hs_code_consistency(sea_shipment, complete_sea_docs)
        assert results == []

    def test_normalizes_hs_code_separators(self, sea_shipment, complete_sea_docs):
        """847130 and 8471.30 should be treated as the same code."""
        docs = list(complete_sea_docs)
        # Replace CI hs_code with dotted format
        docs[1] = DocumentSnapshot(
            doc_type=DocumentType.COMMERCIAL_INVOICE,
            hs_code="8471.30",  # Same chapter as 847130 but with separator
            quantity=100.0,
            quantity_unit="CTN",
            declared_value=50000.0,
            currency="USD",
        )
        results = check_hs_code_consistency(sea_shipment, docs)
        assert results == [], "Dotted HS code should normalize to same value"

    def test_skips_when_only_one_source(self):
        shipment = ShipmentContext(
            reference_number="TF-001",
            origin_country="CN",
            destination_country="AE",
            transport_mode="SEA",
            hs_code=None,  # No declared HS
        )
        docs = [
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST)  # No HS codes
        ]
        results = check_hs_code_consistency(shipment, docs)
        assert results == []

    def test_three_way_mismatch_produces_single_exception(self, sea_shipment):
        """When 3 sources all disagree, we still get exactly one exception."""
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE, hs_code="847130"),
            DocumentSnapshot(doc_type=DocumentType.CERTIFICATE_OF_ORIGIN, hs_code="847141"),
            DocumentSnapshot(doc_type=DocumentType.CUSTOMS_DECLARATION, hs_code="847150"),
        ]
        results = check_hs_code_consistency(sea_shipment, docs)
        assert len(results) == 1
        assert len(results[0].rule_metadata["unique_hs6_values"]) == 3


# ---------------------------------------------------------------------------
# Rule 3: Invalid HS code format
# ---------------------------------------------------------------------------


class TestInvalidHsCode:
    def test_flags_alpha_characters_in_hs_code(self, sea_shipment):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE, hs_code="84A130")
        ]
        results = check_invalid_hs_code(sea_shipment, docs)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.INVALID_HS_CODE

    def test_flags_too_short_hs_code(self):
        shipment = ShipmentContext(
            reference_number="TF-001",
            origin_country="CN",
            destination_country="AE",
            transport_mode="SEA",
            hs_code="8471",  # Only 4 digits — invalid
        )
        results = check_invalid_hs_code(shipment, [])
        assert len(results) == 1

    def test_accepts_6_digit_hs_code(self, sea_shipment):
        results = check_invalid_hs_code(sea_shipment, [])
        assert results == []

    def test_accepts_10_digit_hs_code(self):
        shipment = ShipmentContext(
            reference_number="TF-001",
            origin_country="CN",
            destination_country="AE",
            transport_mode="SEA",
            hs_code="8471300000",  # 10-digit national tariff
        )
        results = check_invalid_hs_code(shipment, [])
        assert results == []


# ---------------------------------------------------------------------------
# Rule 4: Weight discrepancy
# ---------------------------------------------------------------------------


class TestWeightDiscrepancy:
    def test_flags_discrepancy_above_threshold(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, gross_weight_kg=4800.0),  # 4% diff
        ]
        results = check_weight_discrepancy(docs, threshold_pct=2.0)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.WEIGHT_DISCREPANCY
        assert results[0].severity == ExceptionSeverity.HIGH

    def test_no_flag_below_threshold(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, gross_weight_kg=4990.0),  # 0.2% diff
        ]
        results = check_weight_discrepancy(docs, threshold_pct=2.0)
        assert results == []

    def test_critical_severity_above_10_pct(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, gross_weight_kg=4400.0),  # 12% diff
        ]
        results = check_weight_discrepancy(docs)
        assert results[0].severity == ExceptionSeverity.CRITICAL

    def test_boundary_exactly_at_threshold_not_flagged(self):
        # Exactly 2.0% difference
        docs = [
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, gross_weight_kg=4900.0),  # exactly 2%
        ]
        results = check_weight_discrepancy(docs, threshold_pct=2.0)
        assert results == []

    def test_skips_when_weight_missing_from_either_doc(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, gross_weight_kg=None),
        ]
        results = check_weight_discrepancy(docs)
        assert results == []

    def test_uses_airway_bill_when_no_bl(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.AIRWAY_BILL, gross_weight_kg=500.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, gross_weight_kg=450.0),  # 10.5% diff
        ]
        results = check_weight_discrepancy(docs)
        assert len(results) == 1
        assert DocumentType.AIRWAY_BILL in results[0].affected_doc_types


# ---------------------------------------------------------------------------
# Rule 5: Quantity discrepancy
# ---------------------------------------------------------------------------


class TestQuantityDiscrepancy:
    def test_flags_any_quantity_difference(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE, quantity=100.0, quantity_unit="CTN"),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, quantity=99.0, quantity_unit="CTN"),
        ]
        results = check_quantity_discrepancy(docs)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.QUANTITY_DISCREPANCY

    def test_no_flag_when_quantities_match(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE, quantity=100.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, quantity=100.0),
        ]
        results = check_quantity_discrepancy(docs)
        assert results == []

    def test_skips_when_quantity_missing(self):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE, quantity=100.0),
            DocumentSnapshot(doc_type=DocumentType.PACKING_LIST, quantity=None),
        ]
        results = check_quantity_discrepancy(docs)
        assert results == []


# ---------------------------------------------------------------------------
# Rule 6: Value discrepancy
# ---------------------------------------------------------------------------


class TestValueDiscrepancy:
    def test_flags_value_above_threshold(self, sea_shipment):
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.COMMERCIAL_INVOICE,
                declared_value=50000.0,
                currency="USD",
            ),
            DocumentSnapshot(
                doc_type=DocumentType.CUSTOMS_DECLARATION,
                declared_value=45000.0,  # 10% diff
                currency="USD",
            ),
        ]
        results = check_value_discrepancy(sea_shipment, docs, threshold_pct=5.0)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.VALUE_DISCREPANCY

    def test_no_flag_within_threshold(self, sea_shipment):
        docs = [
            DocumentSnapshot(doc_type=DocumentType.COMMERCIAL_INVOICE, declared_value=50000.0, currency="USD"),
            DocumentSnapshot(doc_type=DocumentType.CUSTOMS_DECLARATION, declared_value=49000.0, currency="USD"),  # 2%
        ]
        results = check_value_discrepancy(sea_shipment, docs, threshold_pct=5.0)
        assert results == []


# ---------------------------------------------------------------------------
# Rule 7: Certificate validity
# ---------------------------------------------------------------------------


class TestCertificateValidity:
    def test_flags_expired_certificate(self):
        expired_date = date.today() - timedelta(days=5)
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                reference_number="CO-EXP",
                expiry_date=expired_date,
            )
        ]
        results = check_certificate_validity(docs)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.EXPIRED_CERTIFICATE
        assert results[0].severity == ExceptionSeverity.CRITICAL

    def test_flags_certificate_expiring_within_warning_window(self):
        near_expiry = date.today() + timedelta(days=3)
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                reference_number="CO-SOON",
                expiry_date=near_expiry,
            )
        ]
        results = check_certificate_validity(docs, warning_days=7)
        assert len(results) == 1
        assert results[0].exception_type == ExceptionType.EXPIRING_SOON
        assert results[0].severity == ExceptionSeverity.HIGH

    def test_no_flag_for_valid_certificate(self):
        future_expiry = date.today() + timedelta(days=60)
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                expiry_date=future_expiry,
            )
        ]
        results = check_certificate_validity(docs, warning_days=7)
        assert results == []

    def test_infers_90_day_validity_for_co_without_expiry(self):
        """Arab League CO: validity inferred as 90 days from issue if no expiry_date set."""
        issue_date = date.today() - timedelta(days=95)  # Issued 95 days ago → expired
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                reference_number="CO-AL",
                issue_date=issue_date,
                expiry_date=None,  # No explicit expiry
            )
        ]
        results = check_certificate_validity(docs)
        assert any(r.exception_type == ExceptionType.EXPIRED_CERTIFICATE for r in results)

    def test_co_issued_recently_inferred_as_valid(self):
        issue_date = date.today() - timedelta(days=10)  # Only 10 days old
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                issue_date=issue_date,
                expiry_date=None,
            )
        ]
        results = check_certificate_validity(docs)
        assert results == []

    def test_reference_date_override(self):
        """Passing reference_date lets us test historical scenarios."""
        expiry = date(2025, 1, 15)
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.PHYTOSANITARY_CERTIFICATE,
                expiry_date=expiry,
            )
        ]
        # Check as of 2025-01-20 (5 days after expiry)
        results = check_certificate_validity(docs, reference_date=date(2025, 1, 20))
        assert results[0].exception_type == ExceptionType.EXPIRED_CERTIFICATE


# ---------------------------------------------------------------------------
# Rule 8: Country of origin consistency
# ---------------------------------------------------------------------------


class TestCountryConsistency:
    def test_flags_co_country_mismatch(self, sea_shipment):
        docs = [
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                issuing_country="DE",  # Doesn't match origin_country="CN"
                issue_date=date.today() - timedelta(days=5),
                expiry_date=date.today() + timedelta(days=85),
            )
        ]
        results = check_country_of_origin_consistency(sea_shipment, docs)
        assert any(r.exception_type == ExceptionType.COUNTRY_MISMATCH for r in results)

    def test_no_flag_when_countries_match(self, sea_shipment, complete_sea_docs):
        results = check_country_of_origin_consistency(sea_shipment, complete_sea_docs)
        country_mismatch = [r for r in results if r.exception_type == ExceptionType.COUNTRY_MISMATCH]
        assert country_mismatch == []

    def test_flags_restricted_origin_for_gcc_destination(self):
        shipment = ShipmentContext(
            reference_number="TF-RESTRICTED",
            origin_country="IL",  # Restricted for GCC
            destination_country="SA",
            transport_mode="SEA",
        )
        results = check_country_of_origin_consistency(shipment, [])
        assert any(r.exception_type == ExceptionType.RESTRICTED_ORIGIN for r in results)
        assert results[0].severity == ExceptionSeverity.CRITICAL

    def test_no_restricted_flag_for_non_gcc_destination(self):
        """Restricted rule only applies to GCC/Arab League destinations."""
        shipment = ShipmentContext(
            reference_number="TF-001",
            origin_country="IL",
            destination_country="US",  # Not GCC
            transport_mode="SEA",
        )
        results = check_country_of_origin_consistency(shipment, [])
        restricted = [r for r in results if r.exception_type == ExceptionType.RESTRICTED_ORIGIN]
        assert restricted == []


# ---------------------------------------------------------------------------
# Integration: run_exception_checks
# ---------------------------------------------------------------------------


class TestRunExceptionChecks:
    def test_results_sorted_critical_first(self, sea_shipment, complete_sea_docs):
        """Severity ordering: CRITICAL before HIGH."""
        # Add an expired cert (CRITICAL) and a quantity mismatch (HIGH)
        today = date.today()
        docs = [
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            DocumentSnapshot(
                doc_type=DocumentType.COMMERCIAL_INVOICE,
                hs_code="847130",
                quantity=100.0,
                declared_value=50000.0,
                currency="USD",
            ),
            DocumentSnapshot(
                doc_type=DocumentType.PACKING_LIST,
                gross_weight_kg=5000.0,
                quantity=90.0,  # Mismatch → HIGH
            ),
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                hs_code="847141",  # Mismatch → CRITICAL
                issuing_country="CN",
                issue_date=today - timedelta(days=5),
                expiry_date=today + timedelta(days=85),
            ),
        ]
        results = run_exception_checks(sea_shipment, docs)
        severities = [r.severity for r in results]
        critical_indices = [i for i, s in enumerate(severities) if s == ExceptionSeverity.CRITICAL]
        high_indices = [i for i, s in enumerate(severities) if s == ExceptionSeverity.HIGH]
        if critical_indices and high_indices:
            assert max(critical_indices) < min(high_indices), "CRITICAL exceptions should come before HIGH"

    def test_multiple_independent_exceptions_detected(self, sea_shipment):
        """All rules run independently — multiple exceptions from one shipment."""
        today = date.today()
        docs = [
            # BL present but no CI, PL, CO — triggers missing docs
            DocumentSnapshot(doc_type=DocumentType.BILL_OF_LADING, gross_weight_kg=5000.0),
            # Add a CI with wrong HS code and wrong quantity
            DocumentSnapshot(
                doc_type=DocumentType.COMMERCIAL_INVOICE,
                hs_code="999999",  # Wrong HS
                quantity=50.0,
                declared_value=50000.0,
                currency="USD",
            ),
            DocumentSnapshot(
                doc_type=DocumentType.PACKING_LIST,
                gross_weight_kg=4000.0,  # 20% weight discrepancy
                quantity=100.0,  # quantity mismatch
            ),
            DocumentSnapshot(
                doc_type=DocumentType.CERTIFICATE_OF_ORIGIN,
                hs_code="847130",
                issuing_country="DE",  # Wrong country
                issue_date=today - timedelta(days=100),  # Expired (90-day rule)
            ),
        ]
        results = run_exception_checks(sea_shipment, docs)
        exception_types = {r.exception_type for r in results}
        # Should catch: HS mismatch, weight discrepancy, qty discrepancy, expired CO, country mismatch
        assert ExceptionType.HS_CODE_MISMATCH in exception_types
        assert ExceptionType.WEIGHT_DISCREPANCY in exception_types
        assert ExceptionType.QUANTITY_DISCREPANCY in exception_types
        assert ExceptionType.EXPIRED_CERTIFICATE in exception_types
        assert ExceptionType.COUNTRY_MISMATCH in exception_types

    def test_empty_documents_triggers_all_missing_docs(self, sea_shipment):
        results = run_exception_checks(sea_shipment, [])
        missing = [r for r in results if r.exception_type == ExceptionType.MISSING_REQUIRED_DOC]
        assert len(missing) == 4  # BL, CI, PL, CO all missing for sea shipment

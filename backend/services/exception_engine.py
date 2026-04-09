"""
TradeFlow AI — Exception Detection Engine
==========================================
Stateless, pure-Python module that checks a shipment + its documents against
a set of trade compliance rules and returns a list of flagged exceptions.

Design principles:
- No database calls — caller fetches data and passes it in.
- No side effects — caller decides what to persist.
- Fully unit-testable with plain dataclasses.
- Rules are additive — all checks run independently (no early exit).

GCC / Iraq context baked in:
- Required document sets for sea/air/road imports into GCC + Iraq
- Restricted origin country list per GCC customs union rules
- HS code format validation per WCO standard (6-digit minimum)
- Arab League Certificate of Origin validity window (90 days)
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

from backend.core.config import settings
from backend.models.document import DocumentType
from backend.models.exception_event import ExceptionSeverity, ExceptionType


# ---------------------------------------------------------------------------
# Input / Output dataclasses (no ORM dependency)
# ---------------------------------------------------------------------------


@dataclass
class DocumentSnapshot:
    """Flat view of a document's key fields for rule evaluation."""

    doc_type: str                          # DocumentType value
    reference_number: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    hs_code: Optional[str] = None
    gross_weight_kg: Optional[float] = None
    net_weight_kg: Optional[float] = None
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    declared_value: Optional[float] = None
    currency: Optional[str] = None
    issuing_country: Optional[str] = None   # ISO alpha-2
    # Any extra extracted fields for rules that need them
    extra: dict = field(default_factory=dict)


@dataclass
class ShipmentContext:
    """Flat view of a shipment's key fields for rule evaluation."""

    reference_number: str
    origin_country: str           # ISO alpha-2
    destination_country: str      # ISO alpha-2
    transport_mode: str           # "SEA" | "AIR" | "ROAD" | "RAIL"
    hs_code: Optional[str] = None
    gross_weight_kg: Optional[float] = None
    net_weight_kg: Optional[float] = None
    quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    declared_value: Optional[float] = None
    currency: Optional[str] = None


@dataclass
class ExceptionResult:
    """
    A single detected exception.  Maps 1-to-1 with ExceptionEvent model
    so the router can persist it directly.
    """

    exception_type: str            # ExceptionType value
    severity: str                  # ExceptionSeverity value
    title: str
    description: str
    affected_doc_types: List[str]  # which document types were involved
    rule_metadata: dict            # actual vs expected values, thresholds


# ---------------------------------------------------------------------------
# Rule configuration
# ---------------------------------------------------------------------------

# Minimum required documents per transport mode for GCC / Iraq imports.
# Transport mode -> set of required DocumentType values.
_REQUIRED_DOCS: dict[str, list[str]] = {
    "SEA": [
        DocumentType.BILL_OF_LADING,
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.PACKING_LIST,
        DocumentType.CERTIFICATE_OF_ORIGIN,
    ],
    "AIR": [
        DocumentType.AIRWAY_BILL,
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.PACKING_LIST,
        DocumentType.CERTIFICATE_OF_ORIGIN,
    ],
    "ROAD": [
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.PACKING_LIST,
        DocumentType.CERTIFICATE_OF_ORIGIN,
    ],
    "RAIL": [
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.PACKING_LIST,
        DocumentType.CERTIFICATE_OF_ORIGIN,
    ],
    "MULTIMODAL": [
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.PACKING_LIST,
        DocumentType.CERTIFICATE_OF_ORIGIN,
    ],
}

# GCC + Iraq restricted origin countries (imports generally prohibited).
# This is a simplified list — production should pull from a managed config.
_GCC_RESTRICTED_ORIGINS = {"IL"}  # ISO alpha-2

# Countries that require an Arab League Certificate of Origin
# (as opposed to generic GSP or bilateral CO forms).
_ARAB_LEAGUE_CO_REQUIRED = {"SA", "AE", "KW", "QA", "BH", "OM", "IQ", "JO", "EG"}

# Arab League CO is valid for 90 days from issue date.
_ARAB_LEAGUE_CO_VALIDITY_DAYS = 90

# HS code: 6–10 digits, optionally with a separator after digit 6.
_HS_CODE_RE = re.compile(r"^\d{6,10}$")


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _normalize_hs(hs: Optional[str]) -> Optional[str]:
    """Strip separators and whitespace; return None if blank."""
    if not hs:
        return None
    return re.sub(r"[\s.\-]", "", hs.strip()) or None


def _hs6(hs: Optional[str]) -> Optional[str]:
    """Return the 6-digit HS chapter+heading prefix."""
    normalized = _normalize_hs(hs)
    return normalized[:6] if normalized and len(normalized) >= 6 else normalized


def _pct_diff(a: float, b: float) -> float:
    """Return absolute percentage difference between a and b relative to larger value."""
    if a == 0 and b == 0:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b)) * 100


def _today(reference_date: Optional[date]) -> date:
    return reference_date or datetime.now(timezone.utc).date()


def _docs_by_type(docs: List[DocumentSnapshot]) -> dict[str, List[DocumentSnapshot]]:
    index: dict[str, List[DocumentSnapshot]] = {}
    for doc in docs:
        index.setdefault(doc.doc_type, []).append(doc)
    return index


# ---------------------------------------------------------------------------
# Individual rule implementations
# ---------------------------------------------------------------------------


def check_missing_documents(
    shipment: ShipmentContext,
    docs: List[DocumentSnapshot],
) -> List[ExceptionResult]:
    """Rule 1: Flag required documents that are absent."""
    results: List[ExceptionResult] = []
    present_types = {d.doc_type for d in docs}
    required = _REQUIRED_DOCS.get(shipment.transport_mode.upper(), [])

    for doc_type in required:
        if doc_type not in present_types:
            results.append(
                ExceptionResult(
                    exception_type=ExceptionType.MISSING_REQUIRED_DOC,
                    severity=ExceptionSeverity.HIGH,
                    title=f"Missing required document: {doc_type.replace('_', ' ').title()}",
                    description=(
                        f"Shipment {shipment.reference_number} ({shipment.transport_mode} "
                        f"from {shipment.origin_country} to {shipment.destination_country}) "
                        f"is missing a mandatory {doc_type.replace('_', ' ').lower()}."
                    ),
                    affected_doc_types=[doc_type],
                    rule_metadata={
                        "transport_mode": shipment.transport_mode,
                        "required_doc_type": doc_type,
                        "present_doc_types": sorted(present_types),
                    },
                )
            )
    return results


def check_hs_code_consistency(
    shipment: ShipmentContext,
    docs: List[DocumentSnapshot],
) -> List[ExceptionResult]:
    """
    Rule 2: All HS codes across the shipment record and its documents must
    agree at the 6-digit level.  Mismatches trigger a CRITICAL exception —
    customs will reject or hold the shipment.
    """
    results: List[ExceptionResult] = []

    # Build a map: source_label -> hs6 value, skipping blanks
    hs_sources: dict[str, str] = {}

    if shipment.hs_code:
        normalized = _normalize_hs(shipment.hs_code)
        if normalized:
            hs_sources["shipment_record"] = _hs6(normalized)

    by_type = _docs_by_type(docs)
    for doc_type in [
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.CERTIFICATE_OF_ORIGIN,
        DocumentType.CUSTOMS_DECLARATION,
    ]:
        for i, doc in enumerate(by_type.get(doc_type, [])):
            if doc.hs_code:
                label = doc_type if i == 0 else f"{doc_type}[{i}]"
                hs_sources[label] = _hs6(doc.hs_code)

    if len(hs_sources) < 2:
        return results  # not enough data to compare

    unique_values = set(hs_sources.values())
    if len(unique_values) == 1:
        return results  # all agree

    results.append(
        ExceptionResult(
            exception_type=ExceptionType.HS_CODE_MISMATCH,
            severity=ExceptionSeverity.CRITICAL,
            title="HS code mismatch across documents",
            description=(
                f"Conflicting HS codes detected for shipment {shipment.reference_number}. "
                f"Customs will likely hold or reject the consignment until reconciled. "
                f"Unique codes found: {', '.join(sorted(unique_values))}."
            ),
            affected_doc_types=list(hs_sources.keys()),
            rule_metadata={
                "hs_codes_by_source": hs_sources,
                "unique_hs6_values": sorted(unique_values),
            },
        )
    )
    return results


def check_invalid_hs_code(
    shipment: ShipmentContext,
    docs: List[DocumentSnapshot],
) -> List[ExceptionResult]:
    """Rule 3: Validate HS code format (WCO: 6–10 digits, no letters)."""
    results: List[ExceptionResult] = []

    candidates: list[tuple[str, str]] = []  # (source, raw_value)
    if shipment.hs_code:
        candidates.append(("shipment_record", shipment.hs_code))
    by_type = _docs_by_type(docs)
    for doc_type in [
        DocumentType.COMMERCIAL_INVOICE,
        DocumentType.CERTIFICATE_OF_ORIGIN,
        DocumentType.CUSTOMS_DECLARATION,
    ]:
        for doc in by_type.get(doc_type, []):
            if doc.hs_code:
                candidates.append((doc_type, doc.hs_code))

    for source, raw in candidates:
        normalized = _normalize_hs(raw)
        if normalized and not _HS_CODE_RE.match(normalized):
            results.append(
                ExceptionResult(
                    exception_type=ExceptionType.INVALID_HS_CODE,
                    severity=ExceptionSeverity.HIGH,
                    title=f"Invalid HS code format in {source}",
                    description=(
                        f"HS code '{raw}' in {source} does not conform to the WCO standard "
                        f"(6–10 numeric digits). This will cause customs system rejection."
                    ),
                    affected_doc_types=[source],
                    rule_metadata={"source": source, "raw_value": raw, "normalized": normalized},
                )
            )
    return results


def check_weight_discrepancy(
    docs: List[DocumentSnapshot],
    threshold_pct: float = settings.WEIGHT_DISCREPANCY_THRESHOLD_PCT,
) -> List[ExceptionResult]:
    """
    Rule 4: Compare gross weight between Bill of Lading and Packing List.
    >2% difference (configurable) raises a HIGH exception.
    >10% difference raises CRITICAL.
    """
    results: List[ExceptionResult] = []
    by_type = _docs_by_type(docs)

    transport_doc = (
        by_type.get(DocumentType.BILL_OF_LADING, [])
        or by_type.get(DocumentType.AIRWAY_BILL, [])
    )
    packing_list = by_type.get(DocumentType.PACKING_LIST, [])

    if not transport_doc or not packing_list:
        return results

    bl = transport_doc[0]
    pl = packing_list[0]

    if bl.gross_weight_kg is None or pl.gross_weight_kg is None:
        return results

    pct = _pct_diff(bl.gross_weight_kg, pl.gross_weight_kg)
    if pct <= threshold_pct:
        return results

    severity = ExceptionSeverity.CRITICAL if pct > 10 else ExceptionSeverity.HIGH
    bl_type = DocumentType.BILL_OF_LADING if by_type.get(DocumentType.BILL_OF_LADING) else DocumentType.AIRWAY_BILL

    results.append(
        ExceptionResult(
            exception_type=ExceptionType.WEIGHT_DISCREPANCY,
            severity=severity,
            title=f"Gross weight discrepancy: {pct:.1f}% between {bl_type.replace('_', ' ').title()} and Packing List",
            description=(
                f"{bl_type.replace('_', ' ').title()} states {bl.gross_weight_kg:.3f} kg; "
                f"Packing List states {pl.gross_weight_kg:.3f} kg — "
                f"a {pct:.1f}% difference (threshold: {threshold_pct}%). "
                f"Customs may detain and re-weigh the cargo."
            ),
            affected_doc_types=[bl_type, DocumentType.PACKING_LIST],
            rule_metadata={
                "bl_gross_weight_kg": bl.gross_weight_kg,
                "pl_gross_weight_kg": pl.gross_weight_kg,
                "pct_difference": round(pct, 2),
                "threshold_pct": threshold_pct,
            },
        )
    )
    return results


def check_quantity_discrepancy(
    docs: List[DocumentSnapshot],
) -> List[ExceptionResult]:
    """
    Rule 5: Quantity in Commercial Invoice must match Packing List.
    Any difference (>0) is flagged — these should always agree exactly.
    """
    results: List[ExceptionResult] = []
    by_type = _docs_by_type(docs)

    invoices = by_type.get(DocumentType.COMMERCIAL_INVOICE, [])
    packing_lists = by_type.get(DocumentType.PACKING_LIST, [])

    if not invoices or not packing_lists:
        return results

    ci = invoices[0]
    pl = packing_lists[0]

    if ci.quantity is None or pl.quantity is None:
        return results

    pct = _pct_diff(ci.quantity, pl.quantity)
    if pct == 0:
        return results

    results.append(
        ExceptionResult(
            exception_type=ExceptionType.QUANTITY_DISCREPANCY,
            severity=ExceptionSeverity.HIGH,
            title="Quantity mismatch between Commercial Invoice and Packing List",
            description=(
                f"Commercial Invoice declares {ci.quantity} {ci.quantity_unit or 'units'}; "
                f"Packing List declares {pl.quantity} {pl.quantity_unit or 'units'}. "
                f"These must match exactly for customs clearance."
            ),
            affected_doc_types=[DocumentType.COMMERCIAL_INVOICE, DocumentType.PACKING_LIST],
            rule_metadata={
                "invoice_quantity": ci.quantity,
                "invoice_unit": ci.quantity_unit,
                "packing_list_quantity": pl.quantity,
                "packing_list_unit": pl.quantity_unit,
                "pct_difference": round(pct, 2),
            },
        )
    )
    return results


def check_value_discrepancy(
    shipment: ShipmentContext,
    docs: List[DocumentSnapshot],
    threshold_pct: float = settings.VALUE_DISCREPANCY_THRESHOLD_PCT,
) -> List[ExceptionResult]:
    """
    Rule 6: Declared value in Commercial Invoice vs Customs Declaration.
    >5% difference (configurable) triggers a HIGH exception.
    Under-declaration is a known fraud vector and customs actively scrutinize it.
    """
    results: List[ExceptionResult] = []
    by_type = _docs_by_type(docs)

    invoices = by_type.get(DocumentType.COMMERCIAL_INVOICE, [])
    customs_decls = by_type.get(DocumentType.CUSTOMS_DECLARATION, [])

    if not invoices or not customs_decls:
        return results

    ci = invoices[0]
    cd = customs_decls[0]

    if ci.declared_value is None or cd.declared_value is None:
        return results

    pct = _pct_diff(ci.declared_value, cd.declared_value)
    if pct <= threshold_pct:
        return results

    results.append(
        ExceptionResult(
            exception_type=ExceptionType.VALUE_DISCREPANCY,
            severity=ExceptionSeverity.HIGH,
            title=f"Declared value discrepancy: {pct:.1f}% between Invoice and Customs Declaration",
            description=(
                f"Commercial Invoice value: {ci.currency or ''} {ci.declared_value:,.2f}; "
                f"Customs Declaration value: {cd.currency or ''} {cd.declared_value:,.2f} — "
                f"a {pct:.1f}% difference (threshold: {threshold_pct}%). "
                f"This may trigger a customs value query or penalty."
            ),
            affected_doc_types=[DocumentType.COMMERCIAL_INVOICE, DocumentType.CUSTOMS_DECLARATION],
            rule_metadata={
                "invoice_value": ci.declared_value,
                "invoice_currency": ci.currency,
                "customs_value": cd.declared_value,
                "customs_currency": cd.currency,
                "pct_difference": round(pct, 2),
                "threshold_pct": threshold_pct,
            },
        )
    )
    return results


def check_certificate_validity(
    docs: List[DocumentSnapshot],
    reference_date: Optional[date] = None,
    warning_days: int = settings.CERT_EXPIRY_WARNING_DAYS,
) -> List[ExceptionResult]:
    """
    Rule 7: Check for expired or soon-to-expire certificates.
    - CRITICAL: already expired
    - HIGH: expires within `warning_days` days
    Arab League CO has a fixed 90-day validity from issue_date if no expiry_date set.
    """
    results: List[ExceptionResult] = []
    today = _today(reference_date)

    for doc in docs:
        effective_expiry = doc.expiry_date

        # Infer expiry for Arab League CO if not explicit
        if (
            doc.doc_type == DocumentType.CERTIFICATE_OF_ORIGIN
            and effective_expiry is None
            and doc.issue_date is not None
        ):
            from datetime import timedelta
            effective_expiry = doc.issue_date + timedelta(days=_ARAB_LEAGUE_CO_VALIDITY_DAYS)

        if effective_expiry is None:
            continue

        days_remaining = (effective_expiry - today).days

        if days_remaining < 0:
            results.append(
                ExceptionResult(
                    exception_type=ExceptionType.EXPIRED_CERTIFICATE,
                    severity=ExceptionSeverity.CRITICAL,
                    title=f"Expired document: {doc.doc_type.replace('_', ' ').title()}",
                    description=(
                        f"{doc.doc_type.replace('_', ' ').title()} "
                        f"(ref: {doc.reference_number or 'N/A'}) "
                        f"expired on {effective_expiry.isoformat()} "
                        f"({abs(days_remaining)} days ago). "
                        f"Customs will not accept an expired document."
                    ),
                    affected_doc_types=[doc.doc_type],
                    rule_metadata={
                        "doc_type": doc.doc_type,
                        "reference_number": doc.reference_number,
                        "expiry_date": effective_expiry.isoformat(),
                        "days_overdue": abs(days_remaining),
                    },
                )
            )
        elif days_remaining <= warning_days:
            results.append(
                ExceptionResult(
                    exception_type=ExceptionType.EXPIRING_SOON,
                    severity=ExceptionSeverity.HIGH,
                    title=f"Document expiring in {days_remaining} day(s): {doc.doc_type.replace('_', ' ').title()}",
                    description=(
                        f"{doc.doc_type.replace('_', ' ').title()} "
                        f"(ref: {doc.reference_number or 'N/A'}) "
                        f"expires on {effective_expiry.isoformat()} ({days_remaining} day(s) remaining). "
                        f"Renew before the shipment clears customs."
                    ),
                    affected_doc_types=[doc.doc_type],
                    rule_metadata={
                        "doc_type": doc.doc_type,
                        "reference_number": doc.reference_number,
                        "expiry_date": effective_expiry.isoformat(),
                        "days_remaining": days_remaining,
                        "warning_threshold_days": warning_days,
                    },
                )
            )
    return results


def check_country_of_origin_consistency(
    shipment: ShipmentContext,
    docs: List[DocumentSnapshot],
) -> List[ExceptionResult]:
    """
    Rule 8a: Certificate of Origin issuing_country must match shipment origin_country.
    Rule 8b: Restricted origin countries (e.g. IL for GCC) trigger CRITICAL.
    """
    results: List[ExceptionResult] = []
    by_type = _docs_by_type(docs)

    # 8b — restricted origin (applies regardless of documents)
    if shipment.origin_country.upper() in _GCC_RESTRICTED_ORIGINS:
        if shipment.destination_country.upper() in _ARAB_LEAGUE_CO_REQUIRED:
            results.append(
                ExceptionResult(
                    exception_type=ExceptionType.RESTRICTED_ORIGIN,
                    severity=ExceptionSeverity.CRITICAL,
                    title=f"Restricted origin country: {shipment.origin_country}",
                    description=(
                        f"Imports from {shipment.origin_country} are prohibited for "
                        f"shipments destined to {shipment.destination_country} "
                        f"under GCC/Arab League customs rules. "
                        f"This shipment cannot clear customs."
                    ),
                    affected_doc_types=[],
                    rule_metadata={
                        "origin_country": shipment.origin_country,
                        "destination_country": shipment.destination_country,
                        "restricted_origins": sorted(_GCC_RESTRICTED_ORIGINS),
                    },
                )
            )

    # 8a — CO country vs shipment origin
    for co_doc in by_type.get(DocumentType.CERTIFICATE_OF_ORIGIN, []):
        if co_doc.issuing_country is None:
            continue
        if co_doc.issuing_country.upper() != shipment.origin_country.upper():
            results.append(
                ExceptionResult(
                    exception_type=ExceptionType.COUNTRY_MISMATCH,
                    severity=ExceptionSeverity.HIGH,
                    title="Certificate of Origin country mismatch",
                    description=(
                        f"Certificate of Origin lists issuing country as "
                        f"'{co_doc.issuing_country}', but the shipment origin is "
                        f"'{shipment.origin_country}'. Customs may reject the CO."
                    ),
                    affected_doc_types=[DocumentType.CERTIFICATE_OF_ORIGIN],
                    rule_metadata={
                        "co_issuing_country": co_doc.issuing_country,
                        "shipment_origin_country": shipment.origin_country,
                        "co_reference": co_doc.reference_number,
                    },
                )
            )
    return results


# ---------------------------------------------------------------------------
# Public API — run all checks
# ---------------------------------------------------------------------------


def run_exception_checks(
    shipment: ShipmentContext,
    documents: List[DocumentSnapshot],
    reference_date: Optional[date] = None,
) -> List[ExceptionResult]:
    """
    Run the full exception detection suite against a shipment and its documents.

    Args:
        shipment:        Flat context object for the shipment record.
        documents:       List of flat document snapshots attached to the shipment.
        reference_date:  Override "today" for certificate expiry checks (useful in tests).

    Returns:
        List of ExceptionResult objects ordered by severity (CRITICAL first).
    """
    all_results: List[ExceptionResult] = []

    all_results.extend(check_missing_documents(shipment, documents))
    all_results.extend(check_hs_code_consistency(shipment, documents))
    all_results.extend(check_invalid_hs_code(shipment, documents))
    all_results.extend(check_weight_discrepancy(documents))
    all_results.extend(check_quantity_discrepancy(documents))
    all_results.extend(check_value_discrepancy(shipment, documents))
    all_results.extend(check_certificate_validity(documents, reference_date=reference_date))
    all_results.extend(check_country_of_origin_consistency(shipment, documents))

    # Sort: CRITICAL > HIGH > MEDIUM > LOW
    _order = {
        ExceptionSeverity.CRITICAL: 0,
        ExceptionSeverity.HIGH: 1,
        ExceptionSeverity.MEDIUM: 2,
        ExceptionSeverity.LOW: 3,
    }
    all_results.sort(key=lambda r: _order.get(r.severity, 99))
    return all_results

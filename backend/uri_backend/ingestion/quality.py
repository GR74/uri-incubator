"""Deterministic, non-aggregated source-quality signals."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from uri_backend.ingestion.contracts import NormalizationResult

QualityLevel = Literal["strong", "partial", "warning", "unknown"]


class SourceContext(BaseModel):
    family: str
    has_author: bool = False
    has_source_time: bool = False
    has_native_version: bool = False
    has_reproducibility_links: bool = False


class QualityDimension(BaseModel):
    level: QualityLevel
    explanation: str
    signals: list[str] = Field(default_factory=list)


class SourceQualityReport(BaseModel):
    dimensions: dict[str, QualityDimension]
    privacy_warnings: list[str] = Field(default_factory=list)
    licensing_warnings: list[str] = Field(default_factory=list)
    overall_score: None = None


def _dimension(
    level: QualityLevel, explanation: str, *signals: str
) -> QualityDimension:
    return QualityDimension(level=level, explanation=explanation, signals=list(signals))


def assess_source(
    context: SourceContext, normalization: NormalizationResult
) -> SourceQualityReport:
    """Describe independent review signals; deliberately do not rank a source."""
    parts = normalization.parts
    decision_parts = sum(
        1
        for part in parts
        if any(
            token in part.text.lower()
            for token in ("decision", "because", "chose", "changed")
        )
    )
    addressable = bool(parts) and all(bool(part.locator) for part in parts)
    dimensions = {
        "provenance": (
            _dimension("strong", "Author information is present.", "author_present")
            if context.has_author
            else _dimension("warning", "Author information is absent.", "author_absent")
        ),
        "temporal_fidelity": (
            _dimension(
                "strong", "Source timestamps are present.", "source_time_present"
            )
            if context.has_source_time
            else _dimension(
                "partial", "Source timestamps are absent.", "source_time_absent"
            )
        ),
        "decision_density": (
            _dimension(
                "strong",
                "Decision-oriented language appears in normalized parts.",
                f"decision_parts:{decision_parts}",
            )
            if decision_parts
            else _dimension(
                "partial",
                "No decision-oriented language was detected.",
                "decision_parts:0",
            )
        ),
        "reproducibility_support": (
            _dimension(
                "strong",
                "Reproducibility links are recorded.",
                "reproducibility_links_present",
            )
            if context.has_reproducibility_links
            else _dimension(
                "warning",
                "No reproducibility links are recorded.",
                "reproducibility_links_absent",
            )
        ),
        "parse_completeness": (
            _dimension(
                "strong",
                "Normalization covered all parseable content.",
                "parse_coverage:1.0",
            )
            if normalization.parse_coverage == 1.0
            else _dimension(
                "partial",
                "Normalization covered only part of the source.",
                f"parse_coverage:{normalization.parse_coverage}",
            )
            if normalization.parse_coverage > 0
            else _dimension(
                "warning",
                "Normalization produced no parseable content.",
                "parse_coverage:0.0",
            )
        ),
        "citation_addressability": (
            _dimension(
                "strong",
                "Every normalized part has an exact locator.",
                "all_parts_addressable",
            )
            if addressable
            else _dimension(
                "warning",
                "One or more normalized parts lack an exact locator.",
                "parts_not_fully_addressable",
            )
        ),
        "extraction_confidence": (
            _dimension(
                "strong",
                "Adapter normalized the source without parser warnings.",
                "normalized_without_warnings",
            )
            if normalization.status == "normalized" and not normalization.warnings
            else _dimension(
                "partial",
                "Adapter output includes recoverable parser uncertainty.",
                "normalization_warnings_present",
            )
            if normalization.status == "normalized"
            else _dimension(
                "warning",
                "Adapter did not produce a normalized source.",
                f"normalization_status:{normalization.status}",
            )
        ),
    }
    privacy_warnings = (
        ["Review source for private or participant data before sharing."]
        if context.family in {"conversation", "lab_notebook"}
        else []
    )
    licensing_warnings = (
        ["Confirm reuse rights before redistributing source content."]
        if context.family in {"document", "git", "reference_manifest"}
        else []
    )
    return SourceQualityReport(
        dimensions=dimensions,
        privacy_warnings=privacy_warnings,
        licensing_warnings=licensing_warnings,
    )

from uri_backend.ingestion.contracts import NormalizationResult, NormalizedPart
from uri_backend.ingestion.quality import SourceContext, assess_source
from uri_backend.ingestion.worker import default_adapter_registry


def test_quality_dimensions_are_separate() -> None:
    """Collapsing independent warnings into a score hides a review-relevant gap."""
    report = assess_source(
        SourceContext(family="conversation", has_author=False, has_source_time=True),
        NormalizationResult(
            adapter="conversations",
            adapter_version="1",
            status="normalized",
            parts=[
                NormalizedPart(
                    ordinal=0,
                    kind="message",
                    text="A decision because evidence changed.",
                    locator={"conversation_id": "c1", "message": 1},
                )
            ],
            parse_coverage=1.0,
        ),
    )

    assert set(report.dimensions) == {
        "provenance",
        "temporal_fidelity",
        "decision_density",
        "reproducibility_support",
        "parse_completeness",
        "citation_addressability",
        "extraction_confidence",
    }
    assert report.dimensions["provenance"].level == "warning"
    assert report.dimensions["provenance"].signals == ["author_absent"]
    assert report.overall_score is None


def test_registered_conversation_family_has_a_normalization_adapter() -> None:
    """Selected conversations must converge on the same immutable part pipeline as other sources."""
    adapter = default_adapter_registry().resolve(
        "conversation", "application/vnd.uri.conversation+json"
    )

    assert adapter.name == "conversation"

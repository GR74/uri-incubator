from __future__ import annotations

from pathlib import Path

from uri_backend.ingestion.adapters import AdapterRegistry
from uri_backend.ingestion.adapters.lab_notebooks import LabNotebookAdapter
from uri_backend.ingestion.adapters.manifests import ManifestAdapter
from uri_backend.ingestion.adapters.notebooks import NotebookAdapter
from uri_backend.ingestion.contracts import AdapterInput
from uri_backend.ingestion.privacy import contains_participant_rows

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _input(relative: str, family: str, media_type: str) -> AdapterInput:
    return AdapterInput(artifact_path=FIXTURES / relative, family=family, media_type=media_type)


def test_notebook_preserves_cell_order_execution_and_textual_output() -> None:
    """Reordering cells or dropping execution evidence makes notebook citations unauditable."""
    result = NotebookAdapter().normalize(_input("notebooks/analysis.ipynb", "notebook_run", "application/x-ipynb+json"))

    assert [part.locator["cell"] for part in result.parts] == [1, 2, 3]
    assert result.parts[1].metadata["execution_count"] == 1
    assert "score: 0" in result.parts[1].text
    assert any(warning.code == "rich_output_skipped" for warning in result.warnings)


def test_notebook_rejects_participant_rows_in_metadata_without_value_leakage(tmp_path: Path) -> None:
    marker = "PRIVATE-NOTEBOOK-MARKER"
    artifact = tmp_path / "unsafe.ipynb"
    artifact.write_text(
        '{"nbformat":4,"nbformat_minor":5,"metadata":{"records":[{"participant_id":"'
        + marker
        + '","score":1}]},"cells":[]}',
        encoding="utf-8",
    )

    result = NotebookAdapter().normalize(
        AdapterInput(artifact_path=artifact, family="notebook_run", media_type="application/x-ipynb+json")
    )

    assert result.status == "failed"
    assert result.parts == []
    assert [warning.code for warning in result.warnings] == ["participant_data_disallowed"]
    assert marker not in result.warnings[0].message


def test_nested_list_participant_rows_are_detected_without_rejecting_aggregate_summary() -> None:
    assert contains_participant_rows(
        [[{"participant_id": "PRIVATE-NESTED-MARKER", "score": 1}]]
    )
    assert not contains_participant_rows(
        {"cohort_summary": {"participant_count": 20, "mean_age": 24.5}}
    )


def test_run_json_keeps_zero_and_negative_metrics() -> None:
    """Filtering falsy metrics would silently turn a valid run into invented evidence."""
    result = NotebookAdapter().normalize(_input("notebooks/run.json", "notebook_run", "application/json"))

    assert result.parts[0].metadata["metrics"] == {"accuracy": 0, "delta": -0.25}
    assert result.parts[0].metadata["code_revision"] == "abc123"


def test_run_csv_preserves_schema_neutral_run_fields() -> None:
    """Discarding CSV columns would make an equivalent run record lose its evidence."""
    result = NotebookAdapter().normalize(_input("notebooks/run.csv", "notebook_run", "text/csv"))

    assert result.parts[0].metadata["metrics"] == {"zero": 0, "negative": -1}
    assert result.parts[0].metadata["artifact_refs"] == ["result.csv"]


def test_dataset_manifest_contains_reference_not_raw_rows() -> None:
    """Persisting dataset rows would violate the participant-data ingestion boundary."""
    result = ManifestAdapter().normalize(_input("manifests/dataset.yaml", "reference_manifest", "application/yaml"))

    assert result.parts[0].metadata["accession"] == "synthetic-accession"
    assert result.parts[0].locator == {"accession": "synthetic-accession"}
    assert all("participant_id" not in part.text for part in result.parts)


def test_manifest_rejects_participant_row_like_data(tmp_path: Path) -> None:
    """A row-shaped participant payload must fail closed without echoing its rows."""
    artifact = tmp_path / "unsafe.json"
    artifact.write_text('{"records":[{"participant_id":"do-not-store","age":19}]}', encoding="utf-8")

    result = ManifestAdapter().normalize(AdapterInput(artifact_path=artifact, family="reference_manifest", media_type="application/json"))

    assert result.status == "failed"
    assert result.parts == []
    assert [warning.code for warning in result.warnings] == ["participant_data_disallowed"]
    assert "do-not-store" not in result.warnings[0].message


def test_manifest_rejects_common_participant_table_variants_without_echoing_rows(tmp_path: Path) -> None:
    """Identifier and demographic variants must not bypass the manifest privacy boundary."""
    artifact = tmp_path / "unsafe-variants.json"
    artifact.write_text(
        '{"rows":[{"person_code":"private-row","age_years":19,"measure":-2.5},'
        '{"subject":"private-row-two","trial":2,"score":0}]}',
        encoding="utf-8",
    )

    result = ManifestAdapter().normalize(
        AdapterInput(artifact_path=artifact, family="reference_manifest", media_type="application/json")
    )

    assert result.status == "failed"
    assert result.parts == []
    assert [warning.code for warning in result.warnings] == ["participant_data_disallowed"]
    assert "private-row" not in result.warnings[0].message


def test_manifest_keeps_aggregate_cohort_summary_and_uses_fallback_locator(tmp_path: Path) -> None:
    """Aggregate cohort metadata is allowed and must not be mistaken for participant rows."""
    aggregate = tmp_path / "aggregate.json"
    aggregate.write_text('{"cohort_summary":{"n":20,"mean_age":24.5},"license":"CC0"}', encoding="utf-8")

    result = ManifestAdapter().normalize(
        AdapterInput(artifact_path=aggregate, family="reference_manifest", media_type="application/json")
    )

    assert result.status == "normalized"
    assert result.parts[0].locator == {"manifest": 1}
    assert result.parts[0].metadata["cohort_summary"] == {"n": 20, "mean_age": 24.5}


def test_manifest_allows_aggregate_participant_counts_and_distributions(tmp_path: Path) -> None:
    """Aggregate cohort statistics are not participant rows and must remain ingestible."""
    aggregate = tmp_path / "aggregate-participant-summary.json"
    aggregate.write_text(
        '{"cohort_summary":{"participant_count":20,"mean_age":24.5,'
        '"sex_distribution":{"female":11,"male":9},"cohort_counts":{"control":10,"test":10}}}',
        encoding="utf-8",
    )

    result = ManifestAdapter().normalize(
        AdapterInput(artifact_path=aggregate, family="reference_manifest", media_type="application/json")
    )

    assert result.status == "normalized"
    assert result.parts[0].metadata["cohort_summary"]["participant_count"] == 20


def test_manifest_rejects_a_single_row_shaped_participant_record_without_echo(tmp_path: Path) -> None:
    """A direct participant identifier plus row fields must fail even outside a table container."""
    artifact = tmp_path / "single-participant-record.json"
    artifact.write_text('{"participant":"do-not-store","age":19,"score":0}', encoding="utf-8")

    result = ManifestAdapter().normalize(
        AdapterInput(artifact_path=artifact, family="reference_manifest", media_type="application/json")
    )

    assert result.status == "failed"
    assert [warning.code for warning in result.warnings] == ["participant_data_disallowed"]
    assert "do-not-store" not in result.warnings[0].message


def test_bibtex_preserves_citation_key_and_fields() -> None:
    """Replacing a citation key loses the source's stable reference locator."""
    result = ManifestAdapter().normalize(_input("manifests/references.bib", "reference_manifest", "application/x-bibtex"))

    assert result.parts[0].locator == {"citation_key": "synthetic2026"}
    assert result.parts[0].metadata["fields"]["doi"] == "10.0000/synthetic-reference"


def test_ris_preserves_its_source_identifier(tmp_path: Path) -> None:
    """Substituting a generated identifier disconnects a RIS record from its cited source."""
    artifact = tmp_path / "references.ris"
    artifact.write_text("TY  - JOUR\nID  - synthetic-ris\nTI  - Synthetic RIS\nER  - \n", encoding="utf-8")

    result = ManifestAdapter().normalize(AdapterInput(artifact_path=artifact, family="reference_manifest", media_type="application/x-research-info-systems"))

    assert result.parts[0].locator == {"citation_key": "synthetic-ris"}
    assert result.parts[0].metadata["fields"]["TI"] == ["Synthetic RIS"]


def test_eln_preserves_ordered_sections_and_reports_signature_without_verification() -> None:
    """Treating reported signatures as verified would overstate the provenance record."""
    result = LabNotebookAdapter().normalize(_input("lab_notebooks/entry.json", "lab_notebook", "application/json"))

    assert result.parts[0].locator == {"entry": "eln-synthetic-1", "section": 1}
    assert result.parts[-1].metadata["signatures"] == [{"name": "Ada Example", "status": "reported"}]
    assert result.parts[-1].metadata["signatures_verified"] is False


def test_protocol_steps_are_individually_addressable() -> None:
    """Collapsing protocol steps prevents an audit from naming the executed step."""
    result = LabNotebookAdapter().normalize(_input("lab_notebooks/protocol.html", "lab_notebook", "text/html"))

    assert [part.locator["step"] for part in result.parts if part.kind == "protocol_step"] == [1, 2]


def test_eln_csv_maps_known_fields_and_preserves_uncategorized_notes(tmp_path: Path) -> None:
    """Opaque CSV JSON loses the addressable ELN fields reviewers need to inspect."""
    artifact = tmp_path / "entry.csv"
    artifact.write_text(
        "entry_id,title,section,observation,attachments,deviations,protocol_step,notes\n"
        "csv-1,Synthetic CSV,Preparation,Observed zero,raw.txt,None,Measure twice,Uncategorized provenance\n",
        encoding="utf-8",
    )

    result = LabNotebookAdapter().normalize(
        AdapterInput(artifact_path=artifact, family="lab_notebook", media_type="text/csv")
    )

    assert [(part.kind, part.locator) for part in result.parts] == [
        ("entry_section", {"entry": "csv-1", "section": 1}),
        ("observation", {"entry": "csv-1", "observation": 1}),
        ("attachment", {"entry": "csv-1", "attachment": 1}),
        ("deviation", {"entry": "csv-1", "deviation": 1}),
        ("protocol_step", {"entry": "csv-1", "step": 1}),
        ("observation", {"entry": "csv-1", "observation": 2}),
    ]
    assert result.parts[0].metadata["attachments"] == ["raw.txt"]
    assert result.parts[0].metadata["deviations"] == ["None"]
    assert result.parts[-1].text == "Uncategorized provenance"


def test_eln_text_formats_keep_prose_with_headings_and_steps(tmp_path: Path) -> None:
    """Dropping prose whenever structural markup exists erases the lab-record evidence."""
    markdown = tmp_path / "entry.md"
    markdown.write_text("# Preparation\nKept prose observation.\n1. Measure synthetic signal.\n", encoding="utf-8")
    html = tmp_path / "entry.html"
    html.write_text("<h1>Preparation</h1><p>Kept HTML prose.</p><ol><li>Measure synthetic signal.</li></ol>", encoding="utf-8")

    markdown_result = LabNotebookAdapter().normalize(
        AdapterInput(artifact_path=markdown, family="lab_notebook", media_type="text/markdown")
    )
    html_result = LabNotebookAdapter().normalize(
        AdapterInput(artifact_path=html, family="lab_notebook", media_type="text/html")
    )

    assert "Kept prose observation." in [part.text for part in markdown_result.parts]
    assert "Kept HTML prose." in [part.text for part in html_result.parts]


def test_malformed_adapter_input_has_a_safe_parse_error(tmp_path: Path) -> None:
    """Returning parser internals could expose untrusted source material in operational logs."""
    artifact = tmp_path / "broken.json"
    artifact.write_text("{not json", encoding="utf-8")

    result = LabNotebookAdapter().normalize(AdapterInput(artifact_path=artifact, family="lab_notebook", media_type="application/json"))

    assert result.status == "failed"
    assert result.warnings[0].code == "parse_error"
    assert "not json" not in result.warnings[0].message


def test_registry_resolves_each_research_source_family() -> None:
    """Omitting a registered adapter makes otherwise valid source versions unprocessable."""
    registry = AdapterRegistry([NotebookAdapter(), ManifestAdapter(), LabNotebookAdapter()])

    assert registry.resolve("notebook_run", "application/x-ipynb+json").name == "notebook_run"
    assert registry.resolve("reference_manifest", "application/yaml").name == "reference_manifest"
    assert registry.resolve("lab_notebook", "text/html").name == "lab_notebook"

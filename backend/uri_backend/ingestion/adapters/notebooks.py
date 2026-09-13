"""Deterministic, bounded notebook and run-record normalization."""

from __future__ import annotations

import csv
import json
from typing import Any

import nbformat

from uri_backend.ingestion.contracts import (
    AdapterInput,
    NormalizationResult,
    NormalizationWarning,
    NormalizedPart,
)
from uri_backend.ingestion.privacy import contains_participant_rows

NOTEBOOK_MEDIA_TYPES = frozenset({"application/x-ipynb+json", "application/vnd.jupyter.notebook+json"})
RUN_MEDIA_TYPES = frozenset({"application/json", "text/csv"})
MAX_BYTES = 8 * 1024 * 1024
MAX_CELLS = 10_000
MAX_ROWS = 10_000
MAX_NESTING = 40


class NotebookAdapter:
    name = "notebook_run"
    version = "normalization-v1"

    def supports(self, context: AdapterInput) -> bool:
        return context.family == "notebook_run" and context.media_type in NOTEBOOK_MEDIA_TYPES | RUN_MEDIA_TYPES

    def normalize(self, context: AdapterInput) -> NormalizationResult:
        if not self.supports(context):
            return self._result("unsupported", [], [NormalizationWarning(code="unsupported_notebook_run", message="Unsupported notebook or run source.")], 0.0)
        try:
            raw = context.artifact_path.read_bytes()
            if len(raw) > MAX_BYTES:
                return self._failed("file_too_large", "Notebook or run record exceeds the byte limit.")
            if context.media_type in NOTEBOOK_MEDIA_TYPES:
                return self._notebook(raw)
            return self._run(raw, context.media_type)
        except Exception:  # noqa: BLE001 - parser details can contain source content.
            return self._failed("parse_error", "Notebook or run record could not be parsed.")

    def _notebook(self, raw: bytes) -> NormalizationResult:
        notebook = nbformat.reads(raw.decode("utf-8"), as_version=4)
        if len(notebook.cells) > MAX_CELLS:
            return self._failed("cell_limit_exceeded", "Notebook exceeds the cell limit.")
        if contains_participant_rows(dict(notebook.metadata)):
            return self._failed("participant_data_disallowed", "Participant-row-like data is not allowed in notebook records.")
        for cell in notebook.cells:
            if contains_participant_rows(dict(cell.get("metadata", {}))) or contains_participant_rows(cell.get("outputs", [])):
                return self._failed("participant_data_disallowed", "Participant-row-like data is not allowed in notebook records.")
        parts: list[NormalizedPart] = []
        warnings: list[NormalizationWarning] = []
        for cell_number, cell in enumerate(notebook.cells, start=1):
            text = str(cell.source)
            outputs: list[str] = []
            for output in cell.get("outputs", []):
                if output.get("output_type") == "stream":
                    outputs.append(str(output.get("text", "")))
                elif output.get("output_type") in {"execute_result", "display_data"}:
                    data = output.get("data", {})
                    plain = data.get("text/plain") if isinstance(data, dict) else None
                    if plain is not None:
                        outputs.append("".join(plain) if isinstance(plain, list) else str(plain))
                    if isinstance(data, dict) and any(key not in {"text/plain", "text/markdown", "text/html"} for key in data):
                        warnings.append(NormalizationWarning(code="rich_output_skipped", message=f"Skipped rich output in cell {cell_number}."))
            if outputs:
                text = f"{text}\n\n" + "\n".join(outputs)
            parts.append(NormalizedPart(ordinal=cell_number, kind=f"notebook_{cell.cell_type}", text=text, locator={"cell": cell_number}, metadata={"cell_type": cell.cell_type, "execution_count": cell.get("execution_count"), "cell_metadata": dict(cell.get("metadata", {})), "notebook_metadata": dict(notebook.metadata)}))
        return self._result("normalized", parts, warnings, 1.0)

    def _run(self, raw: bytes, media_type: str) -> NormalizationResult:
        if media_type == "application/json":
            payload: Any = json.loads(raw.decode("utf-8"))
            self._nesting(payload)
            if not isinstance(payload, dict):
                return self._failed("invalid_run_shape", "Run JSON must be an object.")
            if contains_participant_rows(payload):
                return self._failed("participant_data_disallowed", "Participant-row-like data is not allowed in run records.")
            return self._run_part(payload, {"run": 1})
        rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
        if len(rows) > MAX_ROWS:
            return self._failed("row_limit_exceeded", "Run CSV exceeds the row limit.")
        parts: list[NormalizedPart] = []
        for row_number, row in enumerate(rows, start=1):
            row = {
                key: self._csv_value(value)
                for key, value in row.items()
                if key is not None and value is not None
            }
            if contains_participant_rows(row):
                return self._failed("participant_data_disallowed", "Participant-row-like data is not allowed in run records.")
            result = self._run_part(row, {"row": row_number}, ordinal=row_number)
            parts.extend(result.parts)
        return self._result("normalized", parts, [], 1.0 if rows else 0.0)

    def _csv_value(self, value: str) -> Any:
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            return json.loads(stripped)
        return value

    def _run_part(self, payload: dict[str, Any], locator: dict[str, int], ordinal: int = 1) -> NormalizationResult:
        allowed = ("parameters", "environment", "code_revision", "dataset_refs", "metrics", "artifact_refs")
        metadata = {key: payload[key] for key in allowed if key in payload}
        return self._result("normalized", [NormalizedPart(ordinal=ordinal, kind="run", text=json.dumps(metadata, ensure_ascii=True, sort_keys=True), locator=locator, metadata=metadata)], [], 1.0)

    def _nesting(self, value: Any, depth: int = 0) -> None:
        if depth > MAX_NESTING:
            raise ValueError("nesting limit")
        if isinstance(value, dict):
            for child in value.values(): self._nesting(child, depth + 1)
        elif isinstance(value, list):
            for child in value: self._nesting(child, depth + 1)

    def _failed(self, code: str, message: str) -> NormalizationResult:
        return self._result("failed", [], [NormalizationWarning(code=code, message=message)], 0.0)

    def _result(self, status: str, parts: list[NormalizedPart], warnings: list[NormalizationWarning], coverage: float) -> NormalizationResult:
        return NormalizationResult(adapter=self.name, adapter_version=self.version, status=status, parts=parts, warnings=warnings, parse_coverage=coverage)

"""Strict manifest and bibliographic-reference adapters with privacy guards."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from uri_backend.ingestion.contracts import (
    AdapterInput,
    NormalizationResult,
    NormalizationWarning,
    NormalizedPart,
)

MANIFEST_MEDIA_TYPES = frozenset({"application/json", "application/yaml", "text/yaml", "application/x-yaml"})
BIB_MEDIA_TYPES = frozenset({"application/x-bibtex", "application/x-research-info-systems"})
ALLOWLIST = frozenset({"accession", "doi", "version", "cohort_summary", "license", "loader", "checksum", "restrictions", "local_availability"})
MAX_BYTES = 4 * 1024 * 1024
MAX_NESTING = 30


class ManifestAdapter:
    name = "reference_manifest"
    version = "normalization-v1"

    def supports(self, context: AdapterInput) -> bool:
        return context.family == "reference_manifest" and context.media_type in MANIFEST_MEDIA_TYPES | BIB_MEDIA_TYPES

    def normalize(self, context: AdapterInput) -> NormalizationResult:
        if not self.supports(context): return self._result("unsupported", [], [NormalizationWarning(code="unsupported_manifest", message="Unsupported manifest source.")], 0.0)
        try:
            raw = context.artifact_path.read_bytes()
            if len(raw) > MAX_BYTES: return self._failed("file_too_large", "Manifest exceeds the byte limit.")
            text = raw.decode("utf-8")
            if context.media_type == "application/x-bibtex": return self._bibtex(text)
            if context.media_type == "application/x-research-info-systems": return self._ris(text)
            payload = json.loads(text) if context.media_type == "application/json" else yaml.safe_load(text)
            self._nesting(payload)
            if self._participant_rows(payload): return self._failed("participant_data_disallowed", "Participant-row-like data is not allowed in manifests.")
            if not isinstance(payload, dict): return self._failed("invalid_manifest_shape", "Manifest must be an object.")
            metadata = {key: payload[key] for key in ALLOWLIST if key in payload}
            locator = {"accession": str(metadata["accession"])} if "accession" in metadata else {"manifest": 1}
            return self._result("normalized", [NormalizedPart(ordinal=1, kind="dataset_manifest", text=json.dumps(metadata, ensure_ascii=True, sort_keys=True), locator=locator, metadata=metadata)], [], 1.0)
        except Exception:  # noqa: BLE001 - parser details can contain source content.
            return self._failed("parse_error", "Manifest could not be parsed.")

    def _bibtex(self, text: str) -> NormalizationResult:
        entries = re.findall(r"@\w+\s*\{\s*([^,]+),(.*?)\n\}", text, re.DOTALL)
        if not entries: return self._failed("parse_error", "BibTeX contains no complete references.")
        parts = []
        for ordinal, (key, body) in enumerate(entries, start=1):
            fields = {name.lower(): value.strip().strip("{}\"") for name, value in re.findall(r"(\w+)\s*=\s*[\{\"](.*?)[\}\"]\s*,?", body, re.DOTALL)}
            parts.append(NormalizedPart(ordinal=ordinal, kind="bibliographic_reference", text=json.dumps(fields, ensure_ascii=True, sort_keys=True), locator={"citation_key": key.strip()}, metadata={"citation_key": key.strip(), "fields": fields}))
        return self._result("normalized", parts, [], 1.0)

    def _ris(self, text: str) -> NormalizationResult:
        records = [record for record in re.split(r"(?m)^ER  -\s*$", text) if record.strip()]
        parts = []
        for ordinal, record in enumerate(records, start=1):
            fields: dict[str, list[str]] = {}
            for tag, value in re.findall(r"(?m)^([A-Z0-9]{2})  - (.*)$", record): fields.setdefault(tag, []).append(value.rstrip())
            key = (fields.get("ID") or fields.get("DO") or [str(ordinal)])[0]
            parts.append(NormalizedPart(ordinal=ordinal, kind="bibliographic_reference", text=json.dumps(fields, ensure_ascii=True, sort_keys=True), locator={"citation_key": key}, metadata={"citation_key": key, "fields": fields}))
        return self._result("normalized", parts, [], 1.0 if parts else 0.0)

    def _participant_rows(self, value: Any, container: str = "") -> bool:
        if isinstance(value, dict):
            fields = {_field_name(key) for key in value}
            has_person_identifier = any(
                re.search(r"(?:participant|person|subject|patient)", field)
                for field in fields
            )
            has_row_measurement = any(
                re.search(r"(?:age|gender|sex|measure|metric|score|trial|condition|session|response|outcome|value)", field)
                for field in fields
            )
            if has_person_identifier and has_row_measurement:
                return True
            return any(self._participant_rows(child, str(key)) for key, child in value.items())
        if isinstance(value, list):
            records = [item for item in value if isinstance(item, dict)]
            obvious_table = _field_name(container) in {"row", "rows", "record", "records", "table", "tables", "participant", "participants", "subject", "subjects", "patient", "patients"}
            if obvious_table and records and any(self._participant_rows(item, container) for item in records):
                return True
            return any(self._participant_rows(item, container) for item in records)
        return False

    def _nesting(self, value: Any, depth: int = 0) -> None:
        if depth > MAX_NESTING: raise ValueError("nesting limit")
        if isinstance(value, dict):
            for child in value.values(): self._nesting(child, depth + 1)
        elif isinstance(value, list):
            for child in value: self._nesting(child, depth + 1)

    def _failed(self, code: str, message: str) -> NormalizationResult: return self._result("failed", [], [NormalizationWarning(code=code, message=message)], 0.0)
    def _result(self, status: str, parts: list[NormalizedPart], warnings: list[NormalizationWarning], coverage: float) -> NormalizationResult: return NormalizationResult(adapter=self.name, adapter_version=self.version, status=status, parts=parts, warnings=warnings, parse_coverage=coverage)


def _field_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")

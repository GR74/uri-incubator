"""Source-faithful parsers for bounded electronic-lab-notebook exports."""

from __future__ import annotations

import csv
import json
import re
from html import unescape
from typing import Any

from pypdf import PdfReader

from uri_backend.ingestion.contracts import (
    AdapterInput,
    NormalizationResult,
    NormalizationWarning,
    NormalizedPart,
)

ELN_MEDIA_TYPES = frozenset({"application/json", "text/csv", "text/markdown", "text/x-markdown", "text/html", "application/pdf"})
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10_000
MAX_NESTING = 40


class LabNotebookAdapter:
    name = "lab_notebook"
    version = "normalization-v1"

    def supports(self, context: AdapterInput) -> bool:
        return context.family == "lab_notebook" and context.media_type in ELN_MEDIA_TYPES

    def normalize(self, context: AdapterInput) -> NormalizationResult:
        if not self.supports(context): return self._result("unsupported", [], [NormalizationWarning(code="unsupported_lab_notebook", message="Unsupported lab notebook source.")], 0.0)
        try:
            raw = context.artifact_path.read_bytes()
            if len(raw) > MAX_BYTES: return self._failed("file_too_large", "Lab notebook export exceeds the byte limit.")
            if context.media_type == "application/json": return self._json(raw.decode("utf-8"))
            if context.media_type == "text/csv": return self._csv(raw.decode("utf-8"))
            if context.media_type == "application/pdf": return self._text("\n".join(page.extract_text() or "" for page in PdfReader(context.artifact_path).pages), "pdf")
            return self._text(raw.decode("utf-8"), "html" if context.media_type == "text/html" else "markdown")
        except Exception:  # noqa: BLE001 - parser details can contain source content.
            return self._failed("parse_error", "Lab notebook export could not be parsed.")

    def _json(self, text: str) -> NormalizationResult:
        payload: Any = json.loads(text)
        self._nesting(payload)
        entries = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(entry, dict) for entry in entries) or len(entries) > MAX_ROWS: return self._failed("invalid_eln_shape", "ELN JSON has an unsupported shape.")
        parts: list[NormalizedPart] = []
        for entry_number, entry in enumerate(entries, start=1):
            entry_id = str(entry.get("entry_id", entry_number))
            common = {key: entry[key] for key in ("title", "created_at", "updated_at", "attachments", "deviations", "signatures") if key in entry}
            common["signatures_verified"] = False
            sections = entry.get("sections", [])
            if not isinstance(sections, list): return self._failed("invalid_eln_shape", "ELN sections must be ordered records.")
            for section_number, section in enumerate(sections, start=1):
                if not isinstance(section, dict): return self._failed("invalid_eln_shape", "ELN section is invalid.")
                part_text = str(section.get("text", section.get("title", "")))
                parts.append(NormalizedPart(ordinal=len(parts)+1, kind="entry_section", text=part_text, locator={"entry": entry_id, "section": section_number}, metadata={**common, "section_title": section.get("title")}))
            for observation_number, observation in enumerate(entry.get("observations", []), start=1):
                parts.append(NormalizedPart(ordinal=len(parts)+1, kind="observation", text=str(observation), locator={"entry": entry_id, "observation": observation_number}, metadata=common))
            for step_number, step in enumerate(entry.get("protocols", entry.get("protocol_steps", [])), start=1):
                parts.append(NormalizedPart(ordinal=len(parts)+1, kind="protocol_step", text=str(step), locator={"entry": entry_id, "step": step_number}, metadata=common))
        return self._result("normalized", parts, [], 1.0 if parts else 0.0)

    def _csv(self, text: str) -> NormalizationResult:
        rows = list(csv.DictReader(text.splitlines()))
        if len(rows) > MAX_ROWS: return self._failed("row_limit_exceeded", "ELN CSV exceeds the row limit.")
        parts = [NormalizedPart(ordinal=index, kind="entry_row", text=json.dumps(row, ensure_ascii=True, sort_keys=True), locator={"row": index}, metadata={"signatures_verified": False}) for index, row in enumerate(rows, start=1)]
        return self._result("normalized", parts, [], 1.0 if parts else 0.0)

    def _text(self, text: str, format_name: str) -> NormalizationResult:
        if format_name == "html":
            steps = [unescape(re.sub(r"<[^>]+>", "", item)).strip() for item in re.findall(r"<li[^>]*>(.*?)</li>", text, re.IGNORECASE | re.DOTALL)]
            headings = [unescape(re.sub(r"<[^>]+>", "", item)).strip() for item in re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", text, re.IGNORECASE | re.DOTALL)]
        else:
            steps = [match.strip() for match in re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+(.+)$", text)]
            headings = [match.strip() for match in re.findall(r"(?m)^#{1,6}\s+(.+)$", text)]
        parts: list[NormalizedPart] = []
        for section_number, heading in enumerate(headings, start=1): parts.append(NormalizedPart(ordinal=len(parts)+1, kind="entry_section", text=heading, locator={"section": section_number}, metadata={"format": format_name, "signatures_verified": False}))
        for step_number, step in enumerate(steps, start=1): parts.append(NormalizedPart(ordinal=len(parts)+1, kind="protocol_step", text=step, locator={"step": step_number}, metadata={"format": format_name, "signatures_verified": False}))
        if not parts and text.strip(): parts.append(NormalizedPart(ordinal=1, kind="entry_text", text=re.sub(r"<[^>]+>", "", text).strip(), locator={"section": 1}, metadata={"format": format_name, "signatures_verified": False}))
        return self._result("normalized", parts, [], 1.0 if parts else 0.0)

    def _nesting(self, value: Any, depth: int = 0) -> None:
        if depth > MAX_NESTING: raise ValueError("nesting limit")
        if isinstance(value, dict):
            for child in value.values(): self._nesting(child, depth + 1)
        elif isinstance(value, list):
            for child in value: self._nesting(child, depth + 1)

    def _failed(self, code: str, message: str) -> NormalizationResult: return self._result("failed", [], [NormalizationWarning(code=code, message=message)], 0.0)
    def _result(self, status: str, parts: list[NormalizedPart], warnings: list[NormalizationWarning], coverage: float) -> NormalizationResult: return NormalizationResult(adapter=self.name, adapter_version=self.version, status=status, parts=parts, warnings=warnings, parse_coverage=coverage)

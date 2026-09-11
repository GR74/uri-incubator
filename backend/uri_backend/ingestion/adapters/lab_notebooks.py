"""Source-faithful parsers for bounded electronic-lab-notebook exports."""

from __future__ import annotations

import csv
import json
import re
from html import unescape
from html.parser import HTMLParser
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
        parts: list[NormalizedPart] = []
        counters: dict[str, dict[str, int]] = {}
        for row_number, row in enumerate(rows, start=1):
            entry_id = row.get("entry_id") or row.get("record_id") or row.get("id") or str(row_number)
            common = self._entry_metadata(row)
            entry_counters = counters.setdefault(
                entry_id,
                {"section": 0, "observation": 0, "step": 0, "attachment": 0, "deviation": 0},
            )
            for field, value in row.items():
                if not value or field in {"entry_id", "record_id", "id", "title", "created_at", "updated_at", "signatures", "signature"}:
                    continue
                kind, locator_key = self._csv_kind(field)
                entry_counters[locator_key] += 1
                metadata = {**common, "field": field} if kind == "observation" else common
                parts.append(NormalizedPart(ordinal=len(parts) + 1, kind=kind, text=value, locator={"entry": entry_id, locator_key: entry_counters[locator_key]}, metadata=metadata))
        return self._result("normalized", parts, [], 1.0 if parts else 0.0)

    def _entry_metadata(self, row: dict[str, str | None]) -> dict[str, Any]:
        metadata: dict[str, Any] = {"signatures_verified": False}
        for key in ("title", "created_at", "updated_at"):
            if row.get(key): metadata[key] = row[key]
        for singular, plural in (("attachment", "attachments"), ("deviation", "deviations"), ("signature", "signatures")):
            value = row.get(plural) or row.get(singular)
            if value: metadata[plural] = [value]
        return metadata

    def _csv_kind(self, field: str) -> tuple[str, str]:
        normalized = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
        if normalized in {"section", "section_title", "heading"}: return "entry_section", "section"
        if normalized in {"protocol", "protocol_step", "step", "procedure"}: return "protocol_step", "step"
        if normalized in {"attachment", "attachments"}: return "attachment", "attachment"
        if normalized in {"deviation", "deviations"}: return "deviation", "deviation"
        return "observation", "observation"

    def _text(self, text: str, format_name: str) -> NormalizationResult:
        blocks = self._html_blocks(text) if format_name == "html" else self._markdown_blocks(text)
        parts: list[NormalizedPart] = []
        counters = {"section": 0, "observation": 0, "step": 0}
        for kind, block in blocks:
            locator_key = {"entry_section": "section", "protocol_step": "step", "observation": "observation"}[kind]
            counters[locator_key] += 1
            parts.append(NormalizedPart(ordinal=len(parts)+1, kind=kind, text=block, locator={locator_key: counters[locator_key]}, metadata={"format": format_name, "signatures_verified": False}))
        return self._result("normalized", parts, [], 1.0 if parts else 0.0)

    def _markdown_blocks(self, text: str) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped: continue
            if match := re.fullmatch(r"#{1,6}\s+(.+)", stripped): blocks.append(("entry_section", match.group(1)))
            elif match := re.fullmatch(r"(?:\d+[.)]|[-*])\s+(.+)", stripped): blocks.append(("protocol_step", match.group(1)))
            else: blocks.append(("observation", stripped))
        return blocks

    def _html_blocks(self, text: str) -> list[tuple[str, str]]:
        parser = _ELNHTMLParser()
        parser.feed(text)
        parser.close()
        return parser.blocks

    def _nesting(self, value: Any, depth: int = 0) -> None:
        if depth > MAX_NESTING: raise ValueError("nesting limit")
        if isinstance(value, dict):
            for child in value.values(): self._nesting(child, depth + 1)
        elif isinstance(value, list):
            for child in value: self._nesting(child, depth + 1)

    def _failed(self, code: str, message: str) -> NormalizationResult: return self._result("failed", [], [NormalizationWarning(code=code, message=message)], 0.0)
    def _result(self, status: str, parts: list[NormalizedPart], warnings: list[NormalizationWarning], coverage: float) -> NormalizationResult: return NormalizationResult(adapter=self.name, adapter_version=self.version, status=status, parts=parts, warnings=warnings, parse_coverage=coverage)


class _ELNHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[tuple[str, str]] = []
        self._active: tuple[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "li"} or re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self._active = (tag, "entry_section" if tag.startswith("h") else "protocol_step" if tag == "li" else "observation")

    def handle_endtag(self, tag: str) -> None:
        if self._active is not None and self._active[0] == tag: self._flush()

    def handle_data(self, data: str) -> None:
        self._text.append(unescape(data))

    def _flush(self) -> None:
        text = "".join(self._text).strip()
        if text: self.blocks.append((self._active[1] if self._active else "observation", text))
        self._text = []
        self._active = None

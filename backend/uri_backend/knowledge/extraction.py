"""Cited, review-only extraction from normalized source parts."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uri_backend.ingestion.models import ExtractionRun
from uri_backend.knowledge.models import (
    CandidateCitation,
    DraftCandidate,
    DraftRelation,
    DraftRelationCitation,
    DraftSet,
    Record,
)
from uri_backend.knowledge.schemas import (
    CandidateCitationInput,
    ExtractedCandidate,
    ExtractedRelation,
)
from uri_backend.retrieval.providers import (
    ProviderError,
    StructuredGenerationProvider,
    StructuredRequest,
)
from uri_backend.sources.models import ContentPart, SourceVersion

EXTRACTION_PIPELINE_VERSION = "extraction-v1"
SAFE_RESPONSE_KEYS = frozenset({"status_code", "model", "done", "eval_count", "prompt_eval_count", "total_duration"})


@dataclass(frozen=True)
class ExtractionConfig:
    model_id: str
    model_digest: str
    prompt_version: str
    schema_version: str
    parser_version: str
    sampling_config: dict[str, object] = field(default_factory=dict)
    sampling_version: str = "sampling-v1"
    max_window_characters: int = 6000
    pipeline_version: str = EXTRACTION_PIPELINE_VERSION


class CandidateBatch(BaseModel):
    items: list[ExtractedCandidate] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _warning(code: str, **details: object) -> dict[str, object]:
    """Warnings must be deterministic and never include model or source prose."""
    return {"code": code, **details}


def _safe_response_metadata(provider: object) -> dict[str, object]:
    metadata = getattr(provider, "response_metadata", {})
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key in SAFE_RESPONSE_KEYS and isinstance(value, (str, int, float, bool))
    }


def _windows(parts: list[ContentPart], limit: int) -> list[dict[str, object]]:
    if limit <= 0:
        raise ValueError("max_window_characters must be positive")
    windows: list[dict[str, object]] = []
    current: list[dict[str, object]] = []
    current_size = 0
    for part in parts:
        item = {"part_id": str(part.id), "locator": part.locator, "text": part.text}
        size = len(part.text)
        if current and current_size + size > limit:
            windows.append({"parts": current})
            current, current_size = [], 0
        current.append(item)
        current_size += size
    if current:
        windows.append({"parts": current})
    return windows


async def _get_or_create_run(
    session: AsyncSession,
    source_version_id: UUID,
    config: ExtractionConfig,
    ingestion_run_id: UUID | None,
) -> ExtractionRun:
    run = await session.scalar(
        sa.select(ExtractionRun)
        .where(
            ExtractionRun.source_version_id == source_version_id,
            ExtractionRun.pipeline_version == config.pipeline_version,
        )
        .with_for_update()
    )
    if run is None:
        run = ExtractionRun(
            source_version_id=source_version_id,
            ingestion_run_id=ingestion_run_id,
            pipeline_version=config.pipeline_version,
            model_id=config.model_id,
            model_digest=config.model_digest,
            prompt_version=config.prompt_version,
            schema_version=config.schema_version,
            parser_version=config.parser_version,
            sampling_config=config.sampling_config,
            sampling_version=config.sampling_version,
            status="running",
        )
        session.add(run)
        await session.flush()
    else:
        if ingestion_run_id is not None and run.ingestion_run_id is None:
            run.ingestion_run_id = ingestion_run_id
        run.status = "running"
        run.error_code, run.error_detail = None, None
    return run


async def _record_provider_failure(
    session: AsyncSession,
    source_version_id: UUID,
    config: ExtractionConfig,
    ingestion_run_id: UUID | None,
    error: Exception,
) -> None:
    async with session.begin():
        run = await _get_or_create_run(session, source_version_id, config, ingestion_run_id)
        if isinstance(error, ProviderError):
            run.status = "retry" if error.retryable else "failed"
            run.error_code, run.error_detail = error.code, "Provider extraction failed"
        else:
            run.status, run.error_code, run.error_detail = "failed", "internal_error", "Extraction failed"
        run.completed_at = sa.func.now() if run.status == "failed" else None


def _validated_citations(
    citations: list[CandidateCitationInput], parts: dict[UUID, ContentPart]
) -> tuple[list[CandidateCitationInput], str | None]:
    for citation in citations:
        part = parts.get(citation.part_id)
        if part is None:
            return [], "unknown_citation_part"
        if _normalized(citation.quote) not in _normalized(part.text):
            return [], "quote_not_found"
    return citations, None


def _date_is_supported(candidate: ExtractedCandidate, citations: list[CandidateCitationInput], parts: dict[UUID, ContentPart]) -> bool:
    if candidate.event_time is None:
        return True
    return any(
        part.source_time is not None and part.source_time.date() == candidate.event_time.date()
        for citation in citations
        if (part := parts[citation.part_id])
    )


def _actors_are_supported(candidate: ExtractedCandidate, citations: list[CandidateCitationInput], parts: dict[UUID, ContentPart]) -> bool:
    evidence = " ".join(
        f"{parts[citation.part_id].author_label or ''} {parts[citation.part_id].text}".casefold()
        for citation in citations
    )
    return all(_normalized(actor).casefold() in evidence for actor in candidate.actors)


async def extract_candidates(
    session: AsyncSession,
    source_version_id: UUID,
    provider: StructuredGenerationProvider,
    extraction_config: ExtractionConfig,
    *,
    ingestion_run_id: UUID | None = None,
) -> DraftSet:
    """Persist review-only candidates after exact evidence validation.

    The provider call is intentionally outside the persistence transaction; the
    resulting draft, citations, relations, run outcome, and warnings commit as
    one transaction. No published record or graph edge is produced here.
    """
    source_version = await session.get(SourceVersion, source_version_id)
    if source_version is None:
        raise LookupError("Unknown source version")
    parts = list((await session.scalars(
        sa.select(ContentPart).where(ContentPart.source_version_id == source_version_id).order_by(ContentPart.ordinal)
    )).all())
    part_by_id = {part.id: part for part in parts}
    project_id, author_id = source_version.project_id, source_version.created_by
    await session.commit()

    async with session.begin():
        existing = await session.scalar(
            sa.select(DraftSet)
            .join(ExtractionRun, DraftSet.extraction_run_id == ExtractionRun.id)
            .where(
                ExtractionRun.source_version_id == source_version_id,
                ExtractionRun.pipeline_version == extraction_config.pipeline_version,
                ExtractionRun.status == "succeeded",
            )
        )
        if existing is not None:
            existing.extraction_run = await session.scalar(
                sa.select(ExtractionRun).where(ExtractionRun.id == existing.extraction_run_id)
            )
            return existing
        await _get_or_create_run(session, source_version_id, extraction_config, ingestion_run_id)
    try:
        request = StructuredRequest(
            schema=CandidateBatch,
            messages=[
                {
                    "role": "system",
                    "content": "Extract only cited research drafts. Return exact part IDs and short exact quotes. Do not infer relations.",
                },
                {"role": "user", "content": {"windows": _windows(parts, extraction_config.max_window_characters)}},
            ],
        )
        batch = await provider.generate(request)
    except Exception as error:
        await _record_provider_failure(session, source_version_id, extraction_config, ingestion_run_id, error)
        raise

    warnings: list[dict[str, object]] = []
    valid: list[tuple[ExtractedCandidate, list[CandidateCitationInput]]] = []
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    citation_claims: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}
    keys: set[str] = set()
    for candidate in batch.items:
        citations, issue = _validated_citations(candidate.citations, part_by_id)
        if issue:
            warnings.append(_warning(issue, candidate_key=candidate.candidate_key))
            continue
        if not _date_is_supported(candidate, citations, part_by_id):
            warnings.append(_warning("unsupported_event_time", candidate_key=candidate.candidate_key))
            continue
        if not _actors_are_supported(candidate, citations, part_by_id):
            warnings.append(_warning("unsupported_actor", candidate_key=candidate.candidate_key))
            continue
        citation_identity = tuple(sorted((str(item.part_id), _normalized(item.quote)) for item in citations))
        identity = (candidate.candidate_type.value, _normalized(candidate.statement), citation_identity)
        if identity in seen:
            warnings.append(_warning("duplicate_candidate", candidate_key=candidate.candidate_key))
            continue
        conflict_key = (candidate.candidate_type.value, citation_identity)
        earlier = citation_claims.get(conflict_key)
        if earlier is not None and earlier != _normalized(candidate.statement):
            warnings.append(_warning("possible_conflict", candidate_key=candidate.candidate_key))
        citation_claims[conflict_key] = _normalized(candidate.statement)
        if candidate.candidate_key in keys:
            warnings.append(_warning("duplicate_candidate_key", candidate_key=candidate.candidate_key))
            continue
        seen.add(identity)
        keys.add(candidate.candidate_key)
        valid.append((candidate, citations))

    async with session.begin():
        run = await _get_or_create_run(session, source_version_id, extraction_config, ingestion_run_id)
        draft = DraftSet(project_id=project_id, author_id=author_id, extraction_run_id=run.id, candidates=[])
        draft.extraction_run = run
        session.add(draft)
        await session.flush()
        by_key: dict[str, DraftCandidate] = {}
        for candidate, citations in valid:
            persisted = DraftCandidate(
                draft_set_id=draft.id,
                extraction_run_id=run.id,
                candidate_type=candidate.candidate_type,
                statement=candidate.statement,
                payload=candidate.payload.data,
                event_time=candidate.event_time,
                actors=candidate.actors,
                confidence=candidate.confidence,
                uncertainty=candidate.uncertainty,
            )
            session.add(persisted)
            draft.candidates.append(persisted)
            await session.flush()
            session.add_all([CandidateCitation(candidate_id=persisted.id, content_part_id=item.part_id, quote=_normalized(item.quote)) for item in citations])
            by_key[candidate.candidate_key] = persisted
        await session.flush()
        records = {
            record.id: record
            for record in (await session.scalars(sa.select(Record).where(Record.project_id == project_id))).all()
        }
        for relation in batch.relations:
            citations, issue = _validated_citations(relation.citations, part_by_id)
            if issue:
                warnings.append(_warning(issue, relation_type=relation.relation_type.value))
                continue
            source_candidate = by_key.get(relation.source.candidate_key) if relation.source.candidate_key else None
            target_candidate = by_key.get(relation.target.candidate_key) if relation.target.candidate_key else None
            source_record = records.get(relation.source.record_id) if relation.source.record_id else None
            target_record = records.get(relation.target.record_id) if relation.target.record_id else None
            if (relation.source.candidate_key and source_candidate is None) or (relation.target.candidate_key and target_candidate is None) or (relation.source.record_id and source_record is None) or (relation.target.record_id and target_record is None):
                warnings.append(_warning("unknown_relation_endpoint", relation_type=relation.relation_type.value))
                continue
            if (source_candidate and source_candidate.id == getattr(target_candidate, "id", None)) or (source_record and source_record.id == getattr(target_record, "id", None)):
                warnings.append(_warning("identical_relation_endpoints", relation_type=relation.relation_type.value))
                continue
            persisted_relation = DraftRelation(
                draft_set_id=draft.id,
                extraction_run_id=run.id,
                source_candidate_id=getattr(source_candidate, "id", None),
                source_record_id=getattr(source_record, "id", None),
                target_candidate_id=getattr(target_candidate, "id", None),
                target_record_id=getattr(target_record, "id", None),
                relation_type=relation.relation_type,
                statement=relation.statement,
                confidence=relation.confidence,
            )
            session.add(persisted_relation)
            await session.flush()
            session.add_all([DraftRelationCitation(draft_relation_id=persisted_relation.id, content_part_id=item.part_id, quote=_normalized(item.quote)) for item in citations])
        run.status, run.warnings, run.response_metadata = "succeeded", warnings, _safe_response_metadata(provider)
        run.completed_at = sa.func.now()
        await session.flush()
        return draft

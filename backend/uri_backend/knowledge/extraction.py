"""Cited, review-only extraction from normalized source parts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
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
    GenerationCallMetadata,
    GenerationSpec,
    ProviderError,
    ProviderSchemaError,
    StructuredGenerationProvider,
    StructuredRequest,
)
from uri_backend.sources.models import ContentPart, SourceVersion

EXTRACTION_PIPELINE_VERSION = "extraction-v1"
SAFE_RESPONSE_KEYS = frozenset({"status_code", "model", "done", "eval_count", "prompt_eval_count", "total_duration"})


@dataclass(frozen=True)
class ExtractionConfig:
    prompt_version: str
    schema_version: str
    parser_version: str
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


def _candidate_ref(ordinal: int, key: str) -> dict[str, object]:
    return {"candidate_ordinal": ordinal, "candidate_digest": sha256(key.encode()).hexdigest()[:16]}


def _safe_response_metadata(metadata: object) -> dict[str, object]:
    if not isinstance(metadata, Mapping):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key in SAFE_RESPONSE_KEYS
        and isinstance(value, (str, int, float, bool))
        and (not isinstance(value, str) or len(value) <= 300)
    }


def _provider_generation_spec(provider: StructuredGenerationProvider) -> GenerationSpec:
    spec = provider.generation_spec
    if not isinstance(spec, GenerationSpec):
        raise ProviderSchemaError("provider_generation_spec_invalid")
    return spec


def _provider_call_entry(
    provider: StructuredGenerationProvider, window_index: int
) -> tuple[GenerationCallMetadata, dict[str, object]]:
    metadata = provider.last_generation_metadata
    if not isinstance(metadata, GenerationCallMetadata):
        raise ProviderSchemaError("provider_metadata_missing")
    entry = {
        "window_index": window_index,
        "provider_id": metadata.provider_id,
        "model_id": metadata.model_id,
        "model_digest": metadata.model_digest,
        "sampling_config": dict(metadata.sampling_config),
        "sampling_version": metadata.sampling_version,
        "response_metadata": _safe_response_metadata(metadata.response_metadata),
    }
    return metadata, entry


def _metadata_matches_spec(metadata: GenerationCallMetadata, spec: GenerationSpec) -> bool:
    return (
        metadata.provider_id == spec.provider_id
        and metadata.model_id == spec.model_id
        and metadata.model_digest == spec.model_digest
        and metadata.sampling_config == spec.sampling_config
        and metadata.sampling_version == spec.sampling_version
    )


def _windows(parts: list[ContentPart], limit: int) -> list[dict[str, object]]:
    if limit <= 0:
        raise ValueError("max_window_characters must be positive")
    windows: list[dict[str, object]] = []
    current: list[dict[str, object]] = []
    current_size = 0
    for part in parts:
        for offset_start in range(0, len(part.text), limit):
            text = part.text[offset_start : offset_start + limit]
            item = {
                "part_id": str(part.id),
                "locator": part.locator,
                "offset_start": offset_start,
                "offset_end": offset_start + len(text),
                "text": text,
            }
            if current and current_size + len(text) > limit:
                windows.append({"parts": current})
                current, current_size = [], 0
            current.append(item)
            current_size += len(text)
    if current:
        windows.append({"parts": current})
    return windows


async def _get_or_create_run(
    session: AsyncSession,
    source_version_id: UUID,
    config: ExtractionConfig,
    generation_spec: GenerationSpec,
    ingestion_run_id: UUID | None,
    job_id: UUID | None = None,
    attempt: int | None = None,
    worker_id: str | None = None,
) -> ExtractionRun:
    where = [ExtractionRun.job_id == job_id, ExtractionRun.attempt == attempt] if job_id else [ExtractionRun.source_version_id == source_version_id, ExtractionRun.pipeline_version == config.pipeline_version, ExtractionRun.job_id.is_(None)]
    run = await session.scalar(
        sa.select(ExtractionRun)
        .where(*where)
        .with_for_update()
    )
    if run is None:
        run = ExtractionRun(
            source_version_id=source_version_id,
            ingestion_run_id=ingestion_run_id,
            job_id=job_id,
            attempt=attempt,
            worker_id=worker_id,
            pipeline_version=config.pipeline_version,
            provider_id=generation_spec.provider_id,
            model_id=generation_spec.model_id,
            model_digest=generation_spec.model_digest,
            prompt_version=config.prompt_version,
            schema_version=config.schema_version,
            parser_version=config.parser_version,
            sampling_config=dict(generation_spec.sampling_config),
            sampling_version=generation_spec.sampling_version,
            status="running",
        )
        session.add(run)
        await session.flush()
    else:
        run.status = "running"
        run.error_code, run.error_detail = None, None
    return run


async def _record_provider_failure(
    session: AsyncSession,
    source_version_id: UUID,
    config: ExtractionConfig,
    generation_spec: GenerationSpec,
    ingestion_run_id: UUID | None,
    error: Exception,
    claimed_job: object | None = None,
    call_metadata: list[dict[str, object]] | None = None,
) -> None:
    async with session.begin():
        run = await _get_or_create_run(
            session, source_version_id, config, generation_spec, ingestion_run_id,
            getattr(claimed_job, "id", None), getattr(claimed_job, "attempt", None), getattr(claimed_job, "worker_id", None),
        )
        if isinstance(error, ProviderError):
            run.status = "retry" if error.retryable else "failed"
            run.error_code, run.error_detail = error.code, "Provider extraction failed"
        else:
            run.status, run.error_code, run.error_detail = "failed", "internal_error", "Extraction failed"
        run.completed_at = sa.func.now() if run.status == "failed" else None
        run.call_metadata = call_metadata or []
        run.response_metadata = (
            call_metadata[-1]["response_metadata"] if call_metadata else {}
        )


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
    labels = {parts[citation.part_id].author_label.casefold() for citation in citations if parts[citation.part_id].author_label}
    prose = " ".join(parts[citation.part_id].text for citation in citations).casefold()

    def appears_as_phrase(actor: str) -> bool:
        tokens = re.findall(r"[\w'-]+", actor.casefold())
        if not tokens:
            return False
        phrase = r"[\W_]+".join(re.escape(token) for token in tokens)
        return re.search(rf"(?<![\w'-]){phrase}(?![\w'-])", prose) is not None

    return all(actor.casefold() in labels or appears_as_phrase(actor) for actor in candidate.actors)


def _contradicts(left: str, right: str) -> bool:
    """Small explicit heuristic: opposite polarity over two shared content words."""
    left_tokens = set(re.findall(r"\b[\w'-]+\b", left.casefold()))
    right_tokens = set(re.findall(r"\b[\w'-]+\b", right.casefold()))
    negations = {"not", "no", "never", "without", "reject", "rejected"}
    return bool((left_tokens & negations) != (right_tokens & negations) and len((left_tokens & right_tokens) - negations) >= 2)


async def extract_candidates(
    session: AsyncSession,
    source_version_id: UUID,
    provider: StructuredGenerationProvider,
    extraction_config: ExtractionConfig,
    *,
    ingestion_run_id: UUID | None = None,
    claimed_job: object | None = None,
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
    generation_spec = _provider_generation_spec(provider)
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
        await _get_or_create_run(
            session, source_version_id, extraction_config, generation_spec, ingestion_run_id,
            getattr(claimed_job, "id", None), getattr(claimed_job, "attempt", None), getattr(claimed_job, "worker_id", None),
        )
    try:
        merged_items: list[ExtractedCandidate] = []
        merged_relations: list[ExtractedRelation] = []
        call_metadata: list[dict[str, object]] = []
        for window_index, window in enumerate(_windows(parts, extraction_config.max_window_characters)):
            request = StructuredRequest(
                schema=CandidateBatch,
                messages=[
                    {"role": "system", "content": "Extract only cited research drafts. Return exact part IDs and short exact quotes. Do not infer relations."},
                    {"role": "user", "content": window},
                ],
            )
            response = await provider.generate(request)
            metadata, entry = _provider_call_entry(provider, window_index)
            call_metadata.append(entry)
            if not _metadata_matches_spec(metadata, generation_spec):
                raise ProviderSchemaError("provider_metadata_mismatch")
            prefix = f"w{window_index}:"
            merged_items.extend(item.model_copy(update={"candidate_key": prefix + item.candidate_key}) for item in response.items)
            for relation in response.relations:
                source = relation.source.model_copy(update={"candidate_key": prefix + relation.source.candidate_key} if relation.source.candidate_key else {})
                target = relation.target.model_copy(update={"candidate_key": prefix + relation.target.candidate_key} if relation.target.candidate_key else {})
                merged_relations.append(relation.model_copy(update={"source": source, "target": target}))
        batch = CandidateBatch(items=merged_items, relations=merged_relations)
    except Exception as error:
        await _record_provider_failure(
            session,
            source_version_id,
            extraction_config,
            generation_spec,
            ingestion_run_id,
            error,
            claimed_job,
            call_metadata if "call_metadata" in locals() else None,
        )
        raise

    warnings: list[dict[str, object]] = []
    valid: list[tuple[ExtractedCandidate, list[CandidateCitationInput]]] = []
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
    canonical_by_identity: dict[tuple[str, str, tuple[tuple[str, str], ...]], str] = {}
    citation_claims: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}
    type_claims: dict[str, list[str]] = {}
    keys: set[str] = set()
    aliases: dict[str, str] = {}
    for ordinal, candidate in enumerate(batch.items):
        citations, issue = _validated_citations(candidate.citations, part_by_id)
        if issue:
            warnings.append(_warning(issue, **_candidate_ref(ordinal, candidate.candidate_key)))
            continue
        if not _date_is_supported(candidate, citations, part_by_id):
            warnings.append(_warning("unsupported_event_time", **_candidate_ref(ordinal, candidate.candidate_key)))
            continue
        if not _actors_are_supported(candidate, citations, part_by_id):
            warnings.append(_warning("unsupported_actor", **_candidate_ref(ordinal, candidate.candidate_key)))
            continue
        citation_identity = tuple(sorted((str(item.part_id), _normalized(item.quote)) for item in citations))
        identity = (candidate.candidate_type.value, _normalized(candidate.statement), citation_identity)
        if identity in seen:
            aliases[candidate.candidate_key] = canonical_by_identity[identity]
            warnings.append(_warning("duplicate_candidate", **_candidate_ref(ordinal, candidate.candidate_key)))
            continue
        conflict_key = (candidate.candidate_type.value, citation_identity)
        earlier = citation_claims.get(conflict_key)
        if earlier is not None and earlier != _normalized(candidate.statement):
            warnings.append(_warning("possible_conflict", **_candidate_ref(ordinal, candidate.candidate_key)))
        if any(_contradicts(statement, candidate.statement) for statement in type_claims.get(candidate.candidate_type.value, [])):
            warnings.append(_warning("possible_conflict", **_candidate_ref(ordinal, candidate.candidate_key)))
        citation_claims[conflict_key] = _normalized(candidate.statement)
        type_claims.setdefault(candidate.candidate_type.value, []).append(_normalized(candidate.statement))
        if candidate.candidate_key in keys:
            warnings.append(_warning("duplicate_candidate_key", **_candidate_ref(ordinal, candidate.candidate_key)))
            continue
        seen.add(identity)
        canonical_by_identity[identity] = candidate.candidate_key
        keys.add(candidate.candidate_key)
        aliases[candidate.candidate_key] = candidate.candidate_key
        valid.append((candidate, citations))

    async with session.begin():
        if claimed_job is not None:
            from uri_backend.ingestion.queue import owned_claim

            await owned_claim(session, claimed_job)
        run = await _get_or_create_run(
            session, source_version_id, extraction_config, generation_spec, ingestion_run_id,
            getattr(claimed_job, "id", None), getattr(claimed_job, "attempt", None), getattr(claimed_job, "worker_id", None),
        )
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
        for alias, canonical in aliases.items():
            if canonical in by_key:
                by_key[alias] = by_key[canonical]
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
        run.status, run.warnings = "succeeded", warnings
        run.call_metadata = call_metadata
        run.response_metadata = call_metadata[-1]["response_metadata"] if call_metadata else {}
        run.completed_at = sa.func.now()
        await session.flush()
        return draft

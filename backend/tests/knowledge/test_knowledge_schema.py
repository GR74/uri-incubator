from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.knowledge.errors import ImmutableRecordError
from uri_backend.knowledge.models import (
    CandidateCitation,
    DraftCandidate,
    DraftRelation,
    DraftRelationCitation,
    DraftSet,
    Record,
    RecordCitation,
    RecordVersion,
    Relation,
    Supersession,
)
from uri_backend.projects.models import Project, User
from uri_backend.sources.models import Artifact, ContentPart, Source, SourceVersion


@pytest.fixture(autouse=True)
async def clean_knowledge_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE supersessions, relation_citations, relations, "
                "record_citations, record_versions, records, reviews, "
                "draft_relation_citations, draft_relations, candidate_citations, "
                "draft_candidates, draft_sets, source_quality_assessments, "
                "content_parts, source_versions, sources, artifacts, audit_events, "
                "membership_capabilities, project_memberships, projects, labs, users "
                "CASCADE"
            )
        )


@pytest.fixture
async def source_version(db_engine: AsyncEngine) -> SourceVersion:
    project_id, author_id = uuid4(), uuid4()
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                User(id=author_id, display_name="Researcher", is_pilot_actor=True),
                Project(id=project_id, name="Knowledge project"),
                Artifact(sha256="a" * 64, storage_key="aa/" + "a" * 62, byte_size=1),
            ]
        )
        await session.flush()
        artifact = await session.scalar(sa.select(Artifact))
        assert artifact is not None
        source = Source(project_id=project_id, family="document", external_id="notes")
        session.add(source)
        await session.flush()
        result = SourceVersion(
            source_id=source.id,
            project_id=project_id,
            artifact_id=artifact.id,
            family="document",
            external_id="notes",
            native_version="v1",
            media_type="text/plain",
            created_by=author_id,
        )
        session.add(result)
        await session.flush()
        session.add(
            ContentPart(
                source_version_id=result.id,
                ordinal=1,
                kind="paragraph",
                text="The analysis produced a difference.",
                locator={"line_start": 1, "line_end": 1},
            )
        )
        await session.commit()
        return result


async def test_evidence_candidate_requires_a_citation(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Removing the final citation must make evidence-bearing drafts uncommittable."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        draft_set = DraftSet(
            project_id=source_version.project_id,
            author_id=source_version.created_by,
            status="draft",
            version=1,
        )
        session.add(draft_set)
        await session.flush()
        session.add(
            DraftCandidate(
                draft_set_id=draft_set.id,
                candidate_type="result",
                statement="The analysis produced a difference.",
                payload={},
                confidence=0.8,
            )
        )
        with pytest.raises(sa.exc.DBAPIError, match="citation"):
            await session.commit()


async def test_candidate_citation_cannot_cross_projects(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Changing a citation to another project must fail instead of leaking evidence."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        other = Project(name="Other project")
        session.add(other)
        await session.flush()
        draft_set = DraftSet(
            project_id=other.id,
            author_id=source_version.created_by,
            status="draft",
            version=1,
        )
        candidate = DraftCandidate(
            draft_set=draft_set,
            candidate_type="result",
            statement="A separate analysis produced a difference.",
            payload={},
            confidence=0.8,
        )
        session.add_all([draft_set, candidate])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        session.add(
            CandidateCitation(
                candidate_id=candidate.id,
                content_part_id=part_id,
                quote="The analysis produced a difference.",
            )
        )
        with pytest.raises(sa.exc.DBAPIError, match="project"):
            await session.commit()


async def test_draft_relation_requires_citation_and_same_draft_endpoints(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """A relation without evidence or with an endpoint from another set is invalid."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        first = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        second = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        session.add_all([first, second])
        await session.flush()
        left = DraftCandidate(draft_set_id=first.id, candidate_type="result", statement="Left.", payload={}, confidence=0.8)
        right = DraftCandidate(draft_set_id=second.id, candidate_type="result", statement="Right.", payload={}, confidence=0.8)
        session.add_all([left, right])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        session.add_all([
            CandidateCitation(candidate_id=left.id, content_part_id=part_id, quote="The analysis produced a difference."),
            CandidateCitation(candidate_id=right.id, content_part_id=part_id, quote="The analysis produced a difference."),
        ])
        relation = DraftRelation(draft_set_id=first.id, source_candidate_id=left.id, target_candidate_id=right.id, relation_type="supports")
        session.add(relation)
        await session.flush()
        session.add(
            DraftRelationCitation(
                draft_relation_id=relation.id,
                content_part_id=part_id,
                quote="The analysis produced a difference.",
            )
        )
        with pytest.raises(sa.exc.DBAPIError, match="draft set"):
            await session.commit()


async def test_published_record_versions_and_citations_are_append_only(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Editing a published version or its evidence must raise the domain immutability error."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        record = Record(project_id=source_version.project_id, record_type="result")
        session.add(record)
        await session.flush()
        version = RecordVersion(record_id=record.id, version=1, statement="Published result.", payload={})
        session.add(version)
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        citation = RecordCitation(record_version_id=version.id, content_part_id=part_id, quote="The analysis produced a difference.")
        session.add(citation)
        await session.commit()

        version.statement = "rewritten"
        with pytest.raises(ImmutableRecordError):
            await session.commit()
        await session.rollback()

        await session.delete(citation)
        with pytest.raises(ImmutableRecordError):
            await session.commit()


async def test_published_relation_requires_citation_and_valid_record_targets(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """A relation must join distinct records in its project and retain exact evidence."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        first = Record(project_id=source_version.project_id, record_type="result")
        second = Record(project_id=source_version.project_id, record_type="method")
        session.add_all([first, second])
        await session.flush()
        relation = Relation(project_id=source_version.project_id, source_record_id=first.id, target_record_id=second.id, relation_type="supports")
        session.add(relation)
        with pytest.raises(sa.exc.DBAPIError, match="citation"):
            await session.commit()


async def test_supersession_links_later_version_of_same_record(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """A correction must add a later immutable version rather than rewrite history."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        record = Record(project_id=source_version.project_id, record_type="result")
        session.add(record)
        await session.flush()
        first = RecordVersion(record_id=record.id, version=1, statement="First.", payload={})
        second = RecordVersion(record_id=record.id, version=2, statement="Corrected.", payload={})
        session.add_all([first, second])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        session.add_all([
            RecordCitation(record_version_id=first.id, content_part_id=part_id, quote="The analysis produced a difference."),
            RecordCitation(record_version_id=second.id, content_part_id=part_id, quote="The analysis produced a difference."),
        ])
        session.add(Supersession(predecessor_version_id=first.id, successor_version_id=second.id))
        await session.commit()

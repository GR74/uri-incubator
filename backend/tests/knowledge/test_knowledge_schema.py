from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.knowledge.errors import ImmutableRecordError
from uri_backend.knowledge.models import (
    Base,
    CandidateCitation,
    DraftCandidate,
    DraftRelation,
    DraftRelationCitation,
    DraftSet,
    GraphEntity,
    Record,
    RecordCitation,
    RecordVersion,
    Relation,
    RelationCitation,
    Review,
    Supersession,
)
from uri_backend.knowledge.schemas import (
    CandidateCitationInput,
    ExtractedCandidate,
    ExtractedRelation,
    RelationEndpointReference,
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
        first = GraphEntity(project_id=source_version.project_id, entity_type="record", native_id=uuid4())
        second = GraphEntity(project_id=source_version.project_id, entity_type="record", native_id=uuid4())
        session.add_all([first, second])
        await session.flush()
        relation = Relation(project_id=source_version.project_id, source_entity_id=first.id, target_entity_id=second.id, relation_type="supports")
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


def test_extraction_contract_resolves_batch_and_published_relation_endpoints() -> None:
    """Removing a batch key or allowing ambiguous endpoints would make Task 3 unresolvable."""
    candidate = ExtractedCandidate(
        candidate_key="candidate-a",
        candidate_type="result",
        statement="Result.",
        confidence=0.7,
        citations=[CandidateCitationInput(part_id=uuid4(), quote="Result.")],
    )
    assert candidate.candidate_key == "candidate-a"
    assert candidate.citations[0].part_id
    assert CandidateCitationInput(content_part_id=uuid4(), quote="Alias.").part_id
    relation = ExtractedRelation(
        source=RelationEndpointReference(candidate_key="candidate-a"),
        target=RelationEndpointReference(record_id=uuid4()),
        relation_type="supports",
        citations=[CandidateCitationInput(part_id=uuid4(), quote="Result.")],
    )
    assert relation.source.candidate_key == "candidate-a"
    with pytest.raises(ValueError):
        RelationEndpointReference(candidate_key="candidate-a", record_id=uuid4())


async def test_graph_relation_allows_typed_entities_and_only_continued_from_cross_project(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Changing graph endpoints back to records-only would block approved graph edges."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        other = Project(name="Continuation project")
        session.add(other)
        await session.flush()
        source_entity = GraphEntity(project_id=source_version.project_id, entity_type="project", native_id=source_version.project_id)
        target_entity = GraphEntity(project_id=other.id, entity_type="project", native_id=other.id)
        session.add_all([source_entity, target_entity])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        relation = Relation(project_id=source_version.project_id, source_entity_id=source_entity.id, target_entity_id=target_entity.id, relation_type="continued_from")
        session.add(relation)
        await session.flush()
        session.add(RelationCitation(relation_id=relation.id, content_part_id=part_id, quote="The analysis produced a difference."))
        await session.commit()


async def test_database_rejects_published_identity_and_review_mutation(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Direct SQL must not rewrite published identity or reviewer audit history."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        other = Project(name="Other immutable project")
        record = Record(project_id=source_version.project_id, record_type="result")
        draft_set = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        session.add_all([other, record, draft_set])
        await session.flush()
        review = Review(draft_set_id=draft_set.id, draft_version=1, reviewer_id=source_version.created_by, decision="approve")
        session.add(review)
        await session.commit()
        review_id = review.id
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            await session.execute(sa.update(Record).where(Record.id == record.id).values(project_id=other.id))
        await session.rollback()
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            await session.execute(sa.delete(Review).where(Review.id == review_id))


async def test_concurrent_citation_deletes_cannot_leave_an_evidence_candidate_uncited(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Deleting different citations concurrently must serialize on their shared owner."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        draft_set = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        session.add(draft_set)
        await session.flush()
        candidate = DraftCandidate(draft_set_id=draft_set.id, candidate_type="result", statement="Cited.", payload={}, confidence=0.8)
        session.add(candidate)
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        first = CandidateCitation(candidate_id=candidate.id, content_part_id=part_id, quote="The analysis produced a difference.")
        second = CandidateCitation(candidate_id=candidate.id, content_part_id=part_id, quote="A second exact citation.")
        session.add_all([first, second])
        await session.commit()
        candidate_id, first_id, second_id = candidate.id, first.id, second.id

    async def delete_one(citation_id):
        async with factory() as session:
            await session.execute(sa.delete(CandidateCitation).where(CandidateCitation.id == citation_id))
            try:
                await session.commit()
            except sa.exc.DBAPIError as error:
                await session.rollback()
                return error
            return None

    first_result, second_result = await asyncio.gather(delete_one(first_id), delete_one(second_id))
    assert sum(result is None for result in (first_result, second_result)) == 1
    assert any(result is not None and "citation" in str(result) for result in (first_result, second_result))
    async with factory() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(CandidateCitation).where(CandidateCitation.candidate_id == candidate_id)) == 1


async def test_task_one_orm_metadata_matches_migrated_postgres_schema(db_engine: AsyncEngine) -> None:
    """A missing column or FK policy in ORM metadata must be caught before autogenerate drifts."""
    table_names = {
        "draft_sets", "draft_candidates", "candidate_citations", "draft_relations",
        "draft_relation_citations", "reviews", "graph_entities", "records",
        "record_versions", "record_citations", "relations", "relation_citations", "supersessions",
    }
    async with db_engine.connect() as connection:
        def inspect_schema(sync_connection):
            inspector = sa.inspect(sync_connection)
            return {
                table: {
                    "columns": {column["name"]: column["nullable"] for column in inspector.get_columns(table)},
                    "foreign_keys": {(foreign_key["constrained_columns"][0], foreign_key["referred_table"], foreign_key.get("options", {}).get("ondelete")) for foreign_key in inspector.get_foreign_keys(table)},
                }
                for table in table_names
            }
        database = await connection.run_sync(inspect_schema)
    assert table_names <= set(Base.metadata.tables)
    for table_name in table_names:
        model = Base.metadata.tables[table_name]
        assert {column.name: column.nullable for column in model.columns} == database[table_name]["columns"]
        model_foreign_keys = {
            (foreign_key.elements[0].parent.name, foreign_key.elements[0].column.table.name, foreign_key.ondelete)
            for foreign_key in model.foreign_key_constraints
        }
        assert model_foreign_keys == database[table_name]["foreign_keys"]

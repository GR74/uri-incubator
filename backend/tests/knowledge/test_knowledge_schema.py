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


@pytest.fixture(params=[CandidateCitation, DraftRelationCitation], ids=["candidate", "relation"])
async def editable_draft_citations(db_engine: AsyncEngine, source_version: SourceVersion, request):
    """Two citations on one draft owner and a citation on another valid owner."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        draft_set = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        first_candidate = DraftCandidate(draft_set=draft_set, candidate_type="result", statement="One.", payload={}, confidence=0.8)
        second_candidate = DraftCandidate(draft_set=draft_set, candidate_type="result", statement="Two.", payload={}, confidence=0.8)
        session.add_all([draft_set, first_candidate, second_candidate])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        first_candidate_citation = CandidateCitation(candidate_id=first_candidate.id, content_part_id=part_id, quote="First evidence.")
        second_candidate_citation = CandidateCitation(candidate_id=second_candidate.id, content_part_id=part_id, quote="Other evidence.")
        session.add_all([first_candidate_citation, second_candidate_citation])
        if request.param is CandidateCitation:
            first, other = first_candidate_citation, second_candidate_citation
            spare = CandidateCitation(candidate_id=first_candidate.id, content_part_id=part_id, quote="Retained evidence.")
        else:
            first_relation = DraftRelation(draft_set_id=draft_set.id, source_candidate_id=first_candidate.id, target_candidate_id=second_candidate.id, relation_type="supports")
            second_relation = DraftRelation(draft_set_id=draft_set.id, source_candidate_id=second_candidate.id, target_candidate_id=first_candidate.id, relation_type="supports")
            session.add_all([first_relation, second_relation])
            await session.flush()
            first = DraftRelationCitation(draft_relation_id=first_relation.id, content_part_id=part_id, quote="First evidence.")
            spare = DraftRelationCitation(draft_relation_id=first_relation.id, content_part_id=part_id, quote="Retained evidence.")
            other = DraftRelationCitation(draft_relation_id=second_relation.id, content_part_id=part_id, quote="Other evidence.")
        session.add_all([first, spare, other])
        await session.commit()
        return first, spare, other


async def test_orm_allows_draft_citation_quote_and_content_part_edits(
    db_engine: AsyncEngine, source_version: SourceVersion, editable_draft_citations
) -> None:
    """A published-only ORM guard must not block corrections to draft evidence."""
    original, _, _ = editable_draft_citations
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        replacement = ContentPart(source_version_id=source_version.id, ordinal=2, kind="paragraph", text="Corrected evidence.", locator={"line_start": 2, "line_end": 2})
        session.add(replacement)
        await session.flush()
        citation = await session.get(type(original), original.id)
        assert citation is not None
        citation.quote = "Corrected evidence."
        citation.content_part_id = replacement.id
        await session.commit()
        await session.refresh(citation)
        assert citation.quote == "Corrected evidence."
        assert citation.content_part_id == replacement.id


async def test_orm_allows_nonfinal_draft_citation_delete_but_preserves_final_citation(
    db_engine: AsyncEngine, editable_draft_citations
) -> None:
    """Draft deletes reach PostgreSQL, where only loss of the final citation fails."""
    original, spare, _ = editable_draft_citations
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        citation = await session.get(type(original), original.id)
        assert citation is not None
        await session.delete(citation)
        await session.commit()
        assert await session.get(type(original), original.id) is None
        retained = await session.get(type(spare), spare.id)
        assert retained is not None
        await session.delete(retained)
        with pytest.raises(sa.exc.DBAPIError, match="requires a citation"):
            await session.commit()
        await session.rollback()
        assert await session.get(type(spare), spare.id) is not None


async def test_orm_rejects_draft_citation_owner_reparenting(
    db_engine: AsyncEngine, editable_draft_citations
) -> None:
    """Removing the selective owner guard must expose the wrong database error."""
    original, _, other = editable_draft_citations
    owner_key = "candidate_id" if isinstance(original, CandidateCitation) else "draft_relation_id"
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        citation = await session.get(type(original), original.id)
        assert citation is not None
        setattr(citation, owner_key, getattr(other, owner_key))
        with pytest.raises(ImmutableRecordError):
            await session.commit()
        await session.rollback()
        await session.refresh(citation)
        assert getattr(citation, owner_key) == getattr(original, owner_key)


@pytest.mark.parametrize("editable_draft_citations", [DraftRelationCitation], indirect=True)
async def test_database_rejects_draft_relation_set_reassignment(
    db_engine: AsyncEngine, source_version: SourceVersion, editable_draft_citations
) -> None:
    """Changing a draft relation's set must fail even when SQL bypasses ORM guards."""
    citation, _, _ = editable_draft_citations
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        other_project = Project(name="Other draft project")
        session.add(other_project)
        await session.flush()
        other_set = DraftSet(project_id=other_project.id, author_id=source_version.created_by)
        session.add(other_set)
        await session.commit()
        with pytest.raises(sa.exc.DBAPIError, match="draft relation set identity is immutable"):
            await session.execute(sa.update(DraftRelation).where(DraftRelation.id == citation.draft_relation_id).values(draft_set_id=other_set.id))


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


@pytest.mark.parametrize("citation_model", [RecordCitation, RelationCitation], ids=["record", "relation"])
@pytest.mark.parametrize("mutation", ["update", "delete"])
async def test_published_citation_orm_guards_remain_append_only(
    db_engine: AsyncEngine, source_version: SourceVersion, citation_model, mutation: str
) -> None:
    """Restoring draft edits must not permit published citation updates or deletes."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        if citation_model is RecordCitation:
            record = Record(project_id=source_version.project_id, record_type="result")
            session.add(record)
            await session.flush()
            version = RecordVersion(record_id=record.id, version=1, statement="Published.", payload={})
            session.add(version)
            await session.flush()
            citation = RecordCitation(record_version_id=version.id, content_part_id=part_id, quote="Published evidence.")
        else:
            first = GraphEntity(project_id=source_version.project_id, entity_type="project", native_id=source_version.project_id)
            second = GraphEntity(project_id=source_version.project_id, entity_type="source", native_id=source_version.source_id)
            session.add_all([first, second])
            await session.flush()
            relation = Relation(project_id=source_version.project_id, source_entity_id=first.id, target_entity_id=second.id, relation_type="cites")
            session.add(relation)
            await session.flush()
            citation = RelationCitation(relation_id=relation.id, content_part_id=part_id, quote="Published evidence.")
        session.add(citation)
        await session.commit()
        if mutation == "update":
            citation.quote = "Rewritten evidence."
        else:
            await session.delete(citation)
        with pytest.raises(ImmutableRecordError):
            await session.commit()


async def test_published_relation_requires_citation_and_valid_record_targets(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """A relation must join distinct records in its project and retain exact evidence."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        first_record = Record(project_id=source_version.project_id, record_type="result")
        second_record = Record(project_id=source_version.project_id, record_type="method")
        session.add_all([first_record, second_record])
        await session.flush()
        first = GraphEntity(project_id=source_version.project_id, entity_type="record", native_id=first_record.id)
        second = GraphEntity(project_id=source_version.project_id, entity_type="record", native_id=second_record.id)
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
            await session.execute(sa.update(Review).where(Review.id == review_id).values(comment="rewritten"))
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
    """Task-1 models mirror PostgreSQL columns, types, defaults, FKs, and named constraints."""
    table_names = {
        "draft_sets", "draft_candidates", "candidate_citations", "draft_relations",
        "draft_relation_citations", "reviews", "graph_entities", "records",
        "record_versions", "record_citations", "relations", "relation_citations", "supersessions",
    }
    async with db_engine.connect() as connection:
        def normalized(value: object | None) -> str | None:
            if value is None:
                return None
            return " ".join(
                str(value).lower()
                .replace("::character varying", "")
                .replace("timestamp with time zone", "timestamp")
                .replace("double precision", "float")
                .replace("'", "")
                .split()
            )

        def inspect_schema(sync_connection):
            inspector = sa.inspect(sync_connection)
            return {
                table: {
                    "columns": {
                        column["name"]: (column["nullable"], normalized(column["type"]), normalized(column.get("default")))
                        for column in inspector.get_columns(table)
                    },
                    "foreign_keys": {(foreign_key["constrained_columns"][0], foreign_key["referred_table"], foreign_key.get("options", {}).get("ondelete")) for foreign_key in inspector.get_foreign_keys(table)},
                    "unique_constraints": {(constraint["name"], tuple(constraint["column_names"])) for constraint in inspector.get_unique_constraints(table)},
                    "check_constraints": {constraint["name"] for constraint in inspector.get_check_constraints(table)},
                }
                for table in table_names
            }
        database = await connection.run_sync(inspect_schema)
    assert table_names <= set(Base.metadata.tables)
    for table_name in table_names:
        model = Base.metadata.tables[table_name]
        model_columns = {
            column.name: (column.nullable, normalized(column.type.compile(dialect=sa.dialects.postgresql.dialect())), normalized(column.server_default.arg if column.server_default else None))
            for column in model.columns
        }
        assert model_columns == database[table_name]["columns"]
        model_foreign_keys = {
            (foreign_key.elements[0].parent.name, foreign_key.elements[0].column.table.name, foreign_key.ondelete)
            for foreign_key in model.foreign_key_constraints
        }
        assert model_foreign_keys == database[table_name]["foreign_keys"]
        assert {(constraint.name, tuple(column.name for column in constraint.columns)) for constraint in model.constraints if isinstance(constraint, sa.UniqueConstraint)} == database[table_name]["unique_constraints"]
        assert {constraint.name for constraint in model.constraints if isinstance(constraint, sa.CheckConstraint)} == database[table_name]["check_constraints"]


async def test_database_rejects_draft_citation_reparenting_and_phantom_graph_entities(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Moving evidence or inventing a typed node must fail at the database boundary."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        draft_set = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        session.add(draft_set)
        await session.flush()
        first = DraftCandidate(draft_set_id=draft_set.id, candidate_type="result", statement="One.", payload={}, confidence=0.8)
        second = DraftCandidate(draft_set_id=draft_set.id, candidate_type="result", statement="Two.", payload={}, confidence=0.8)
        session.add_all([first, second])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        first_citation = CandidateCitation(candidate_id=first.id, content_part_id=part_id, quote="The analysis produced a difference.")
        second_citation = CandidateCitation(candidate_id=second.id, content_part_id=part_id, quote="Second.")
        session.add_all([first_citation, second_citation])
        await session.commit()
        with pytest.raises(sa.exc.DBAPIError, match="owner is immutable"):
            await session.execute(sa.update(CandidateCitation).where(CandidateCitation.id == first_citation.id).values(candidate_id=second.id))
        await session.rollback()
        session.add(GraphEntity(project_id=source_version.project_id, entity_type="record", native_id=uuid4()))
        with pytest.raises(sa.exc.DBAPIError, match="record graph entity"):
            await session.commit()


async def test_database_rejects_draft_relation_citation_reparenting(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Draft-relation evidence cannot be moved between independently cited edges."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        draft_set = DraftSet(project_id=source_version.project_id, author_id=source_version.created_by)
        first = DraftCandidate(draft_set=draft_set, candidate_type="result", statement="One.", payload={}, confidence=0.8)
        second = DraftCandidate(draft_set=draft_set, candidate_type="result", statement="Two.", payload={}, confidence=0.8)
        session.add_all([draft_set, first, second])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        first_candidate_citation = CandidateCitation(candidate_id=first.id, content_part_id=part_id, quote="The analysis produced a difference.")
        second_candidate_citation = CandidateCitation(candidate_id=second.id, content_part_id=part_id, quote="Second candidate evidence.")
        first_relation = DraftRelation(draft_set_id=draft_set.id, source_candidate_id=first.id, target_candidate_id=second.id, relation_type="supports")
        second_relation = DraftRelation(draft_set_id=draft_set.id, source_candidate_id=second.id, target_candidate_id=first.id, relation_type="supports")
        session.add_all([first_candidate_citation, second_candidate_citation, first_relation, second_relation])
        await session.flush()
        citation = DraftRelationCitation(draft_relation_id=first_relation.id, content_part_id=part_id, quote="Relation evidence.")
        session.add_all([citation, DraftRelationCitation(draft_relation_id=second_relation.id, content_part_id=part_id, quote="Other relation evidence.")])
        await session.commit()
        with pytest.raises(sa.exc.DBAPIError, match="owner is immutable"):
            await session.execute(sa.update(DraftRelationCitation).where(DraftRelationCitation.id == citation.id).values(draft_relation_id=second_relation.id))


async def test_database_rejects_cross_project_graph_entities(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Typed native entities cannot be registered in a project that does not own them."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        other = Project(name="Unrelated graph project")
        session.add(other)
        await session.flush()
        source_id = await session.scalar(sa.select(Source.id).where(Source.project_id == source_version.project_id))
        assert source_id is not None
        session.add(GraphEntity(project_id=other.id, entity_type="source", native_id=source_id))
        with pytest.raises(sa.exc.DBAPIError, match="source graph entity"):
            await session.commit()


async def test_database_rejects_cross_and_third_project_relation_endpoints(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Ordinary edges stay local and continued_from starts in its new project, never a third one."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        predecessor = Project(name="Predecessor project")
        third = Project(name="Third graph project")
        session.add_all([predecessor, third])
        await session.flush()
        source_project_entity = GraphEntity(project_id=source_version.project_id, entity_type="project", native_id=source_version.project_id)
        predecessor_entity = GraphEntity(project_id=predecessor.id, entity_type="project", native_id=predecessor.id)
        session.add_all([source_project_entity, predecessor_entity])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        relation = Relation(project_id=third.id, source_entity_id=source_project_entity.id, target_entity_id=predecessor_entity.id, relation_type="continued_from")
        session.add(relation)
        await session.flush()
        session.add(RelationCitation(relation_id=relation.id, content_part_id=part_id, quote="The analysis produced a difference."))
        with pytest.raises(sa.exc.DBAPIError, match="relation endpoints"):
            await session.commit()


async def test_database_rejects_ordinary_cross_project_relation_endpoints(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """A normal relation cannot borrow a graph entity from another project."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        other = Project(name="Foreign endpoint project")
        session.add(other)
        await session.flush()
        local_entity = GraphEntity(project_id=source_version.project_id, entity_type="project", native_id=source_version.project_id)
        foreign_entity = GraphEntity(project_id=other.id, entity_type="project", native_id=other.id)
        session.add_all([local_entity, foreign_entity])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        relation = Relation(project_id=source_version.project_id, source_entity_id=local_entity.id, target_entity_id=foreign_entity.id, relation_type="supports")
        session.add(relation)
        await session.flush()
        session.add(RelationCitation(relation_id=relation.id, content_part_id=part_id, quote="The analysis produced a difference."))
        with pytest.raises(sa.exc.DBAPIError, match="relation endpoints"):
            await session.commit()


async def test_database_rejects_backward_and_cross_record_supersessions(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Supersession may only point forward within one stable record."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        first_record = Record(project_id=source_version.project_id, record_type="result")
        second_record = Record(project_id=source_version.project_id, record_type="result")
        session.add_all([first_record, second_record])
        await session.flush()
        first = RecordVersion(record_id=first_record.id, version=1, statement="Old.", payload={})
        later = RecordVersion(record_id=first_record.id, version=2, statement="New.", payload={})
        other = RecordVersion(record_id=second_record.id, version=1, statement="Other.", payload={})
        session.add_all([first, later, other])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        session.add_all([
            RecordCitation(record_version_id=first.id, content_part_id=part_id, quote="The analysis produced a difference."),
            RecordCitation(record_version_id=later.id, content_part_id=part_id, quote="The analysis produced a difference."),
            RecordCitation(record_version_id=other.id, content_part_id=part_id, quote="The analysis produced a difference."),
        ])
        session.add(Supersession(predecessor_version_id=later.id, successor_version_id=first.id))
        with pytest.raises(sa.exc.DBAPIError, match="supersession"):
            await session.commit()


async def test_database_rejects_cross_record_supersession(
    db_engine: AsyncEngine, source_version: SourceVersion
) -> None:
    """Direct SQL cannot create a supersession between unrelated stable records."""
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        first_record = Record(project_id=source_version.project_id, record_type="result")
        second_record = Record(project_id=source_version.project_id, record_type="result")
        session.add_all([first_record, second_record])
        await session.flush()
        first = RecordVersion(record_id=first_record.id, version=1, statement="One.", payload={})
        second = RecordVersion(record_id=second_record.id, version=2, statement="Two.", payload={})
        session.add_all([first, second])
        await session.flush()
        part_id = await session.scalar(sa.select(ContentPart.id))
        assert part_id is not None
        session.add_all([
            RecordCitation(record_version_id=first.id, content_part_id=part_id, quote="The analysis produced a difference."),
            RecordCitation(record_version_id=second.id, content_part_id=part_id, quote="The analysis produced a difference."),
            Supersession(predecessor_version_id=first.id, successor_version_id=second.id),
        ])
        with pytest.raises(sa.exc.DBAPIError, match="supersession"):
            await session.commit()

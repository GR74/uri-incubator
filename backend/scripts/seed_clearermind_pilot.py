"""Create fictional, local-only ClearerMind pilot metadata without importing evidence."""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from uri_backend.config import Settings
from uri_backend.database import create_engine
from uri_backend.projects.models import AuditEvent, Project, ProjectMembership, User


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register local pilot metadata only; this command never imports source content."
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--start-commit", required=True)
    parser.add_argument("--end-commit", required=True)
    parser.add_argument(
        "--conversation-id",
        action="append",
        required=True,
        help="Explicitly selected conversation identifier; repeat for every selection.",
    )
    parser.add_argument("--project-name", default="ClearerMind local pilot metadata")
    return parser.parse_args()


async def seed(args: argparse.Namespace) -> None:
    if not all(
        [
            args.repository.strip(),
            args.ref.strip(),
            args.start_commit.strip(),
            args.end_commit.strip(),
            *[identifier.strip() for identifier in args.conversation_id],
        ]
    ):
        raise ValueError(
            "All evidence-selection inputs must be explicit and non-empty."
        )
    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError("URI_DATABASE_URL is required for local pilot metadata.")
    engine = create_engine(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            actor = User(
                display_name="Fictional ClearerMind local pilot owner",
                is_pilot_actor=True,
            )
            project = Project(name=args.project_name)
            session.add_all([actor, project])
            await session.flush()
            session.add(
                ProjectMembership(user_id=actor.id, project_id=project.id, role="owner")
            )
            session.add(
                AuditEvent(
                    actor_id=actor.id,
                    project_id=project.id,
                    action="pilot.evidence_selection_declared",
                    target_type="project",
                    target_id=project.id,
                    metadata_={
                        "repository": args.repository,
                        "ref": args.ref,
                        "start_commit": args.start_commit,
                        "end_commit": args.end_commit,
                        "selected_conversation_ids": args.conversation_id,
                        "source_imported": False,
                    },
                )
            )
            await session.commit()
        print(
            f"Created fictional local metadata project {project.id}; no evidence was imported."
        )
    finally:
        await engine.dispose()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed(arguments()))


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    is_pilot_actor: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    lab_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("labs.id"), nullable=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    state: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_membership_user"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("projects.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class MembershipCapability(Base):
    __tablename__ = "membership_capabilities"
    __table_args__ = (
        sa.UniqueConstraint(
            "membership_id", "capability", name="uq_membership_capability"
        ),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("project_memberships.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    allowed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("projects.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    target_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

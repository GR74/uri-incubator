from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lab_id: UUID | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    state: str
    lab_id: UUID | None


class MembershipCreate(BaseModel):
    user_id: UUID
    role: str = Field(pattern="^(owner|student_lead|contributor|reviewer|guest)$")


class MembershipResponse(BaseModel):
    id: UUID
    user_id: UUID
    project_id: UUID
    role: str
    is_active: bool


class PilotActorResponse(BaseModel):
    id: UUID
    display_name: str

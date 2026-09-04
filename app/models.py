import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("ADMIN", "DESIGN_REVIEWER", "COMMERCIAL_REVIEWER", name="user_role"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TermsVersion(Base):
    __tablename__ = "terms_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    terms_type: Mapped[str] = mapped_column(
        Enum("SUBMISSION_TERMS", "SUPPLY_ENQUIRY_TERMS", name="terms_type"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("terms_type", "version", name="uq_terms_type_version"),)


class SequenceCounter(Base):
    __tablename__ = "sequence_counters"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reference_number: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    track: Mapped[str] = mapped_column(
        Enum("DESIGNER", "MANUFACTURER", "BRAND", name="submission_track"), nullable=False
    )
    # Plain text, not a Postgres ENUM: the state machine is still being locked down
    # stage by stage (Stage 4 adds more values) and a native enum needs a migration
    # to add each new value — a validated free-text column keeps that cheap for now.
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    terms_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("terms_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SubmissionDetail(Base):
    __tablename__ = "submission_detail"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("submission_id", "stage", name="uq_submission_stage"),)


class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    stage: Mapped[str] = mapped_column(
        Enum("SCREENING", "DESIGN_ASSESSMENT", "COMMERCIAL_ASSESSMENT", name="checklist_stage"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    items: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("stage", "version", name="uq_checklist_stage_version"),)


class ChecklistResponse(Base):
    __tablename__ = "checklist_responses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    checklist_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_templates.id"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    checked_items: Mapped[dict] = mapped_column(JSONB, nullable=False)
    all_checked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StageDecision(Base):
    __tablename__ = "stage_decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    decision_type: Mapped[str] = mapped_column(
        Enum("AUTO_ADVANCE", "APPROVE_ANYWAY", "REJECT", name="decision_type"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    checklist_response_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checklist_responses.id"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StageAttachment(Base):
    __tablename__ = "stage_attachments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    # Nullable: public submitters (Designer/Manufacturer intake) have no `users`
    # row at all — only a staff upload (Stage 4, not built yet) would set this.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    file_key: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SLAClock(Base):
    __tablename__ = "sla_clocks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    clock_type: Mapped[str] = mapped_column(
        Enum("ACK_48H", "SCREEN_10BD", "EVAL_30BD", name="sla_clock_type"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("ACTIVE", "MET", "BREACHED", "CANCELLED", name="sla_clock_status"),
        nullable=False,
        default="ACTIVE",
    )

    __table_args__ = (UniqueConstraint("submission_id", "clock_type", name="uq_submission_clock_type"),)


class DeclinedIPRegister(Base):
    __tablename__ = "declined_ip_register"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    reference_number: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitter_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    declined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decline_reason: Mapped[str] = mapped_column(String, nullable=False)


class DealShapeDecision(Base):
    __tablename__ = "deal_shape_decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    deal_shape: Mapped[str] = mapped_column(
        Enum("CO_DEVELOPMENT", "SELL_IP_ROYALTY", "LICENSE", "BUYOUT", name="deal_shape"),
        nullable=False,
    )
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

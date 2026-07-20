from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    prompt_text: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    default_output_count: Mapped[int] = mapped_column(Integer, default=1)
    max_output_count: Mapped[int] = mapped_column(Integer, default=10)
    model: Mapped[str] = mapped_column(String(80), default="gpt-image-2")
    size: Mapped[str] = mapped_column(String(40), default="1024x1536")
    quality: Mapped[str] = mapped_column(String(20), default="high")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    assets: Mapped[list[TemplateAsset]] = relationship(
        back_populates="template", cascade="all, delete-orphan", order_by="TemplateAsset.order_index"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="template")


class TemplateAsset(Base):
    __tablename__ = "template_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(80), default="scene_reference")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    template: Mapped[Template] = relationship(back_populates="assets")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    source_channel: Mapped[str] = mapped_column(String(40), default="web")
    output_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), index=True, default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assets_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped[Template] = relationship(back_populates="jobs")
    assets: Mapped[list[JobAsset]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobAsset.order_index"
    )


class JobAsset(Base):
    __tablename__ = "job_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # input | output
    role: Mapped[str] = mapped_column(String(80), default="identity")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="assets")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Моя AI-платформа")
    slug: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    tagline: Mapped[str] = mapped_column(
        String(240), default="Персональные нейрофотосессии по готовым шаблонам"
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[str] = mapped_column(String(120), default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    viewport: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=lambda: {"x": 80.0, "y": 80.0, "zoom": 1.0}
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    nodes: Mapped[list[ProjectNode]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectNode.created_at"
    )
    generations: Mapped[list[CanvasGeneration]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class ProjectNode(Base):
    __tablename__ = "project_nodes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    node_type: Mapped[str] = mapped_column(String(20), index=True)  # photo | prompt
    title: Mapped[str] = mapped_column(String(180), default="")
    x: Mapped[float] = mapped_column(default=0.0)
    y: Mapped[float] = mapped_column(default=0.0)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="nodes")
    assets: Mapped[list[ProjectAsset]] = relationship(
        back_populates="node", cascade="all, delete-orphan", order_by="ProjectAsset.created_at"
    )
    generations: Mapped[list[CanvasGeneration]] = relationship(
        back_populates="prompt_node", cascade="all, delete-orphan"
    )


class CanvasGeneration(Base):
    __tablename__ = "canvas_generations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    prompt_node_id: Mapped[str] = mapped_column(
        ForeignKey("project_nodes.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True, default="queued")
    output_count: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="generations")
    prompt_node: Mapped[ProjectNode] = relationship(back_populates="generations")
    assets: Mapped[list[ProjectAsset]] = relationship(
        back_populates="generation", cascade="all, delete-orphan",
        passive_deletes=True, order_by="ProjectAsset.order_index"
    )


class ProjectAsset(Base):
    __tablename__ = "project_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("project_nodes.id", ondelete="CASCADE"), index=True
    )
    generation_id: Mapped[str | None] = mapped_column(
        ForeignKey("canvas_generations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), index=True)  # customer_photo | reference | output
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[ProjectNode] = relationship(back_populates="assets")
    generation: Mapped[CanvasGeneration | None] = relationship(back_populates="assets")

class ProviderCredential(Base):
    __tablename__ = "provider_credentials"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    connection_mode: Mapped[str] = mapped_column(String(40), default="direct")  # direct | integrator
    api_base_url: Mapped[str] = mapped_column(String(500), default="")
    model_name: Mapped[str] = mapped_column(String(160), default="")
    auth_header: Mapped[str] = mapped_column(String(100), default="Authorization")
    auth_prefix: Mapped[str] = mapped_column(String(40), default="Bearer")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="operator")  # owner | operator | viewer
    allowed_project_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GenerationMetric(Base):
    __tablename__ = "generation_metrics"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    generation_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    prompt_node_id: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="mock", index=True)
    model: Mapped[str] = mapped_column(String(100), default="")
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

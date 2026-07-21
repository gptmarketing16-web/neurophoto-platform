from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class TemplateAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    order_index: int
    original_filename: str
    mime_type: str


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    prompt_text: str
    input_schema: dict
    default_output_count: int
    max_output_count: int
    model: str
    size: str
    quality: str
    is_active: bool
    created_at: datetime
    assets: list[TemplateAssetOut]


class JobAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    role: str
    order_index: int
    original_filename: str
    mime_type: str
    url: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str
    customer_name: str
    source_channel: str
    output_count: int
    status: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    assets_deleted_at: datetime | None
    assets: list[JobAssetOut]


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    slug: str
    tagline: str
    is_public: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceUpsert(BaseModel):
    display_name: str
    slug: str
    tagline: str = "Персональные нейрофотосессии по готовым шаблонам"
    is_public: bool = True


class SlugAvailabilityOut(BaseModel):
    requested: str
    normalized: str
    available: bool
    reason: str | None = None


class ProjectCreate(BaseModel):
    title: str
    description: str = ""
    theme: str = ""
    project_type: str = "user"
    tags: list[str] = Field(default_factory=list)


class ProjectPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    theme: str | None = None
    project_type: str | None = None
    tags: list[str] | None = None
    viewport: dict | None = None


class NodeCreate(BaseModel):
    node_type: str
    x: float = 100.0
    y: float = 100.0
    title: str | None = None


class NodePatch(BaseModel):
    title: str | None = None
    x: float | None = None
    y: float | None = None
    config: dict | None = None


class NodeDuplicateRequest(BaseModel):
    offset_x: float = 40.0
    offset_y: float = 40.0


class ProjectManualSave(BaseModel):
    project: dict = Field(default_factory=dict)
    nodes: list[dict] = Field(default_factory=list)


class GenerateNodeRequest(BaseModel):
    output_count: int | None = None


class ProjectSummaryOut(BaseModel):
    id: str
    title: str
    description: str
    theme: str
    tags: list[str]
    photo_count: int
    prompt_count: int
    created_at: datetime
    updated_at: datetime


class AutomationOrderCreate(BaseModel):
    external_order_id: str
    customer_name: str = ""
    source: str = ""
    theme: str
    generation_numbers: list[int] = Field(default_factory=list)
    priority: int = 100
    payload: dict = Field(default_factory=dict)


class AutomationOrderStatusPatch(BaseModel):
    status: str
    error_message: str | None = None

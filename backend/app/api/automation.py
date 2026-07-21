from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_owner
from ..db import get_db
from ..models import AutomationOrder, Project
from ..schemas import AutomationOrderCreate, AutomationOrderStatusPatch
from ..services.idgen import new_id
from ..settings import settings

router = APIRouter(tags=["automation"])

ACTIVE_STATUSES = {"assigned", "preparing", "generating", "delivering"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ALLOWED_STATUSES = {"queued", *ACTIVE_STATUSES, *TERMINAL_STATUSES, "needs_review"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_theme(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _check_automation_token(
    authorization: Annotated[str | None, Header()] = None,
    x_neurophoto_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = (settings.automation_api_token or settings.max_webhook_secret or settings.app_secret_key or "").strip()
    if not expected:
        raise HTTPException(503, "Токен автоматизации не настроен")
    supplied = (x_neurophoto_token or "").strip()
    if not supplied and authorization:
        prefix, _, token = authorization.partition(" ")
        if prefix.lower() == "bearer":
            supplied = token.strip()
    if supplied != expected:
        raise HTTPException(401, "Неверный токен автоматизации")


def _order_out(order: AutomationOrder) -> dict:
    return {
        "id": order.id,
        "external_order_id": order.external_order_id,
        "customer_name": order.customer_name,
        "source": order.source,
        "theme": order.theme,
        "generation_numbers": order.generation_numbers or [],
        "status": order.status,
        "assigned_project_id": order.assigned_project_id,
        "priority": order.priority,
        "error_message": order.error_message,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "started_at": order.started_at,
        "completed_at": order.completed_at,
    }


def _free_agent_project(db: Session, theme: str) -> Project | None:
    normalized = _normalize_theme(theme)
    projects = db.scalars(
        select(Project)
        .where(Project.project_type == "agent")
        .order_by(Project.created_at.asc())
    ).all()
    candidates = [project for project in projects if _normalize_theme(project.theme) == normalized]
    for project in candidates:
        active = db.scalar(
            select(func.count(AutomationOrder.id)).where(
                AutomationOrder.assigned_project_id == project.id,
                AutomationOrder.status.in_(ACTIVE_STATUSES),
            )
        ) or 0
        if not active:
            return project
    return None


def _assign_order_if_possible(db: Session, order: AutomationOrder) -> None:
    if order.assigned_project_id or order.status != "queued":
        return
    project = _free_agent_project(db, order.theme)
    if project:
        order.assigned_project_id = project.id
        order.status = "assigned"
        order.started_at = utcnow()
        order.updated_at = utcnow()


def _assign_next_for_theme(db: Session, theme: str) -> AutomationOrder | None:
    next_order = db.scalar(
        select(AutomationOrder)
        .where(
            AutomationOrder.status == "queued",
            func.lower(AutomationOrder.theme) == _normalize_theme(theme),
        )
        .order_by(AutomationOrder.priority.asc(), AutomationOrder.created_at.asc())
    )
    if not next_order:
        # PostgreSQL lower() comparison above will not normalize whitespace; use Python fallback.
        queued = db.scalars(
            select(AutomationOrder)
            .where(AutomationOrder.status == "queued")
            .order_by(AutomationOrder.priority.asc(), AutomationOrder.created_at.asc())
        ).all()
        next_order = next((item for item in queued if _normalize_theme(item.theme) == _normalize_theme(theme)), None)
    if next_order:
        _assign_order_if_possible(db, next_order)
    return next_order


@router.post("/api/automation/orders", status_code=202, dependencies=[Depends(_check_automation_token)])
def receive_automation_order(payload: AutomationOrderCreate, db: Session = Depends(get_db)) -> dict:
    external_order_id = payload.external_order_id.strip()
    theme = payload.theme.strip()
    if not external_order_id:
        raise HTTPException(422, "external_order_id обязателен")
    if not theme:
        raise HTTPException(422, "theme обязателен")
    numbers = []
    for value in payload.generation_numbers:
        number = int(value)
        if number > 0 and number not in numbers:
            numbers.append(number)
    if not numbers:
        raise HTTPException(422, "Нужно передать хотя бы один номер генерации")

    existing = db.scalar(
        select(AutomationOrder).where(AutomationOrder.external_order_id == external_order_id)
    )
    if existing:
        return _order_out(existing)

    order = AutomationOrder(
        id=new_id("ord"),
        external_order_id=external_order_id,
        customer_name=payload.customer_name.strip(),
        source=payload.source.strip().lower(),
        theme=theme,
        generation_numbers=numbers,
        priority=max(0, min(1000, int(payload.priority))),
        payload=dict(payload.payload or {}),
        status="queued",
    )
    db.add(order)
    db.flush()
    _assign_order_if_possible(db, order)
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.get("/api/automation/orders")
def list_automation_orders(
    user: CurrentUser,
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[dict]:
    require_owner(user)
    query = select(AutomationOrder).order_by(
        AutomationOrder.priority.asc(), AutomationOrder.created_at.desc()
    )
    if status:
        query = query.where(AutomationOrder.status == status)
    orders = db.scalars(query.limit(max(1, min(500, limit)))).all()
    return [_order_out(order) for order in orders]


@router.patch("/api/automation/orders/{order_id}")
def update_automation_order(
    order_id: str,
    payload: AutomationOrderStatusPatch,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict:
    require_owner(user)
    order = db.get(AutomationOrder, order_id)
    if not order:
        raise HTTPException(404, "Заказ не найден")
    status = payload.status.strip().lower()
    if status not in ALLOWED_STATUSES:
        raise HTTPException(422, "Неизвестный статус")
    old_project_id = order.assigned_project_id
    order.status = status
    order.error_message = payload.error_message
    order.updated_at = utcnow()
    if status in TERMINAL_STATUSES:
        order.completed_at = utcnow()
        order.assigned_project_id = None
    elif status in ACTIVE_STATUSES and not order.started_at:
        order.started_at = utcnow()
    db.flush()
    if status in TERMINAL_STATUSES and old_project_id:
        project = db.get(Project, old_project_id)
        if project:
            _assign_next_for_theme(db, project.theme)
    db.commit()
    db.refresh(order)
    return _order_out(order)

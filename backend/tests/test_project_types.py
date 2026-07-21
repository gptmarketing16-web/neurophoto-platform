from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.automation import _normalize_theme
from app.auth import assert_project_access
from app.schemas import ProjectCreate


def user(role: str):
    return SimpleNamespace(role=role, allowed_project_ids=['p1'])


def test_agent_project_is_read_only_for_operator():
    with pytest.raises(HTTPException) as error:
        assert_project_access(user('operator'), 'p1', write=True, project_type='agent')
    assert error.value.status_code == 403


def test_owner_can_edit_agent_project():
    assert_project_access(user('owner'), 'p1', write=True, project_type='agent')


def test_theme_normalization_for_queue():
    assert _normalize_theme('  СВО   Семья ') == 'сво семья'


def test_project_create_accepts_users_base_for_agent_payload():
    payload = ProjectCreate(title='СВО — конвейер 2', project_type='agent', base_project_id='prj_source')
    assert payload.base_project_id == 'prj_source'


def test_project_create_base_is_optional():
    payload = ProjectCreate(title='Пустой проект')
    assert payload.base_project_id is None

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.automation import _normalize_theme
from app.auth import assert_project_access


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

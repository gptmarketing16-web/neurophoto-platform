import pytest

from app.services.slug import normalize_slug, validate_slug


def test_normalize_slug():
    assert normalize_slug(" URA SMM-AI Platform ") == "ura_smm_ai_platform"


def test_validate_slug():
    assert validate_slug("ura_smm_ai_platform") == "ura_smm_ai_platform"


@pytest.mark.parametrize("value", ["api", "ab", "___", "Привет"])
def test_invalid_slug(value: str):
    with pytest.raises(ValueError):
        validate_slug(value)

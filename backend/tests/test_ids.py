from app.services.idgen import new_id


def test_ids_are_prefixed_and_unique():
    first = new_id("tpl")
    second = new_id("tpl")
    assert first.startswith("tpl_")
    assert first != second

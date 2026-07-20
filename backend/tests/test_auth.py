from app.auth import hash_password, verify_password


def test_password_hash_round_trip():
    encoded = hash_password("VeryStrong123!")
    assert encoded != "VeryStrong123!"
    assert verify_password("VeryStrong123!", encoded)
    assert not verify_password("wrong-password", encoded)

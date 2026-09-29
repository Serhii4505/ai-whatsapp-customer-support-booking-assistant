import pytest

from app.whatsapp.errors import InvalidSignatureError
from app.whatsapp.security import compute_signature, verify_challenge, verify_signature


def test_valid_signature_is_accepted() -> None:
    body = b'{"synthetic":true}'
    signature = compute_signature(body, "test-secret")
    verify_signature(body, signature, "test-secret")


@pytest.mark.parametrize("signature", [None, "", "sha1=deadbeef", "sha256=abc", "sha256=" + "0" * 64])
def test_invalid_signature_is_rejected(signature: str | None) -> None:
    with pytest.raises(InvalidSignatureError):
        verify_signature(b'{"synthetic":true}', signature, "test-secret")


def test_challenge_requires_mode_and_matching_token() -> None:
    assert verify_challenge("subscribe", "token-123", "token-123")
    assert not verify_challenge("unsubscribe", "token-123", "token-123")
    assert not verify_challenge("subscribe", "wrong", "token-123")


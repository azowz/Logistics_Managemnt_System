"""HMAC signing + API-key / secret crypto tests (no DB)."""

from __future__ import annotations

from app.integrations import crypto


def test_api_key_generate_verify_roundtrip():
    plaintext, prefix, key_hash = crypto.generate_api_key()
    assert plaintext.startswith("mesaar_")
    assert crypto.extract_key_prefix(plaintext) == prefix
    assert crypto.verify_api_key(plaintext, key_hash)
    assert not crypto.verify_api_key("mesaar_deadbeef_wrong", key_hash)
    assert not crypto.verify_api_key("", key_hash)


def test_key_hash_is_not_reversible_and_differs_from_plaintext():
    plaintext, _, key_hash = crypto.generate_api_key()
    assert key_hash != plaintext
    assert plaintext not in key_hash


def test_webhook_secret_encrypt_decrypt_roundtrip():
    secret = crypto.generate_webhook_secret()
    enc = crypto.encrypt_secret(secret)
    assert enc != secret
    assert crypto.decrypt_secret(enc) == secret
    assert crypto.decrypt_secret("not-a-token") is None


def test_signature_verifies_and_detects_tampering():
    secret = crypto.generate_webhook_secret()
    body = '{"event":"shipment.delivered","data":{"shipment_id":"abc"}}'
    sig = crypto.compute_signature(secret, body)
    assert sig.startswith("sha256=")
    assert crypto.verify_signature(secret, body, sig)
    assert not crypto.verify_signature(secret, body + " ", sig)      # body tamper
    assert not crypto.verify_signature("other-secret", body, sig)    # wrong secret
    assert not crypto.verify_signature(secret, body, "sha256=deadbeef")


def test_signature_with_timestamp_binds_time():
    secret = crypto.generate_webhook_secret()
    body = "payload"
    sig = crypto.compute_signature(secret, body, timestamp="1000")
    assert crypto.verify_signature(secret, body, sig, timestamp="1000")
    assert not crypto.verify_signature(secret, body, sig, timestamp="2000")
    assert not crypto.verify_signature(secret, body, sig)  # missing timestamp on verify


def test_verify_rejects_empty_inputs():
    assert not crypto.verify_signature("", "b", "sha256=x")
    assert not crypto.verify_signature("s", "b", "")

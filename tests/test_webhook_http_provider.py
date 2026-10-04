"""Real HTTP webhook provider tests (httpx MockTransport — no network)."""

from __future__ import annotations

import httpx

from app.integrations.delivery import HttpWebhookProvider


def _provider(handler):
    return HttpWebhookProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _headers():
    return {"X-Mesaar-Signature": "sha256=abc", "X-Mesaar-Event": "shipment.delivered",
            "X-Mesaar-Delivery-Id": "d1", "X-Mesaar-Idempotency-Key": "k1"}


def test_2xx_is_success_and_sends_headers():
    seen = {}

    def handler(req):
        seen.update(dict(req.headers))
        return httpx.Response(200, text="ok")

    r = _provider(handler).send(target_url="https://p/hook", body='{"a":1}', headers=_headers(), timeout_seconds=5)
    assert r.succeeded and r.http_status_code == 200 and r.response_body == "ok"
    assert seen["x-mesaar-signature"] == "sha256=abc"
    assert seen["x-mesaar-idempotency-key"] == "k1"
    assert "Mesaar-Webhooks" in seen["user-agent"]


def test_4xx_and_5xx_are_failures():
    r4 = _provider(lambda req: httpx.Response(404, text="nope")).send(
        target_url="https://p/h", body="{}", headers=_headers(), timeout_seconds=5)
    r5 = _provider(lambda req: httpx.Response(503, text="down")).send(
        target_url="https://p/h", body="{}", headers=_headers(), timeout_seconds=5)
    assert not r4.succeeded and r4.http_status_code == 404 and r4.error_code == "http_404"
    assert not r5.succeeded and r5.http_status_code == 503 and r5.error_code == "http_503"


def test_timeout_is_failure():
    def handler(req):
        raise httpx.TimeoutException("timed out")

    r = _provider(handler).send(target_url="https://p/h", body="{}", headers=_headers(), timeout_seconds=1)
    assert not r.succeeded and r.error_code == "timeout"


def test_connection_error_is_failure():
    def handler(req):
        raise httpx.ConnectError("connection refused")

    r = _provider(handler).send(target_url="https://p/h", body="{}", headers=_headers(), timeout_seconds=1)
    assert not r.succeeded and r.error_code == "connection_error"


def test_long_response_body_is_truncated():
    r = _provider(lambda req: httpx.Response(500, text="x" * 9000)).send(
        target_url="https://p/h", body="{}", headers=_headers(), timeout_seconds=5)
    assert not r.succeeded and len(r.response_body) == 2048


def test_provider_does_not_retry_internally():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(500, text="err")

    _provider(handler).send(target_url="https://p/h", body="{}", headers=_headers(), timeout_seconds=5)
    assert calls["n"] == 1  # exactly one HTTP call; retry is the worker's job

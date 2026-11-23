"""تظل تسميات Prometheus محدودة حتى مع مسارات عشوائية غير موجودة."""

from fastapi import FastAPI
from starlette.requests import Request

from app.observability.metrics import _resolve_route_template


def _request(app: FastAPI, path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "app": app})


def test_unknown_paths_share_one_metric_label():
    app = FastAPI()
    labels = {_resolve_route_template(_request(app, f"/missing/{index}")) for index in range(100)}
    assert labels == {"unmatched"}


def test_known_paths_use_route_template():
    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"id": item_id}

    assert _resolve_route_template(_request(app, "/items/123")) == "/items/{item_id}"

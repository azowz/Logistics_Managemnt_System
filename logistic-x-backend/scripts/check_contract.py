"""Conservative v1 compatibility gate: existing operations and schemas stay intact.

New paths, methods and components are allowed. Any alteration of an existing
operation/schema requires compatibility review, including additive alterations.
The immutable migration baseline must not be regenerated to hide a break.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parents[1] / "api"


def compatibility_errors(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    errors = []
    for path, operations in baseline["paths"].items():
        for method, operation in operations.items():
            if current.get("paths", {}).get(path, {}).get(method) != operation:
                errors.append(f"Changed or removed operation: {method.upper()} {path}")
    for section, components in baseline.get("components", {}).items():
        for name, component in components.items():
            if current.get("components", {}).get(section, {}).get(name) != component:
                errors.append(f"Changed or removed component: {section}/{name}")
    for key in ("security", "servers", "openapi"):
        if baseline.get(key) != current.get(key):
            errors.append(f"Changed global contract: {key}")
    return errors


def main() -> None:
    from app.main import app

    current = app.openapi()
    snapshot = json.loads((API_DIR / "openapi.json").read_text(encoding="utf-8"))
    baseline = json.loads((API_DIR / "openapi.v1.baseline.json").read_text(encoding="utf-8"))
    errors = compatibility_errors(baseline, current)
    if current != snapshot:
        errors.append("api/openapi.json is stale; run python -m scripts.export_openapi")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"OpenAPI snapshot and v1 baseline compatible ({len(current['paths'])} paths)")


if __name__ == "__main__":
    main()

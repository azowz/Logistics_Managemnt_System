"""Export the real API without connecting to database, Redis or frontend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    from app.main import app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("api/openapi.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Exported OpenAPI to {args.output}")


if __name__ == "__main__":
    main()

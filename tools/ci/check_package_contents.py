"""Validate the public wheel/sdist contract without shell glob assumptions."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

REQUIRED_WHEEL_FILES = {
    "agent_state_gate/__init__.py",
    "src/__init__.py",
}
FORBIDDEN_PARTS = {
    ".coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "deep-research",
    "/docs/birdseye/",
}


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("expected exactly one wheel and one sdist")

    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_names = set(archive.namelist())
    missing = REQUIRED_WHEEL_FILES - wheel_names
    if missing:
        raise SystemExit(f"wheel is missing public packages: {sorted(missing)}")

    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_names = [member.name.lower() for member in archive.getmembers()]
    leaked = sorted(
        name
        for name in sdist_names
        if any(forbidden.lower() in name for forbidden in FORBIDDEN_PARTS)
    )
    if leaked:
        raise SystemExit(f"sdist contains forbidden files: {leaked}")

    print(f"validated {wheels[0].name} and {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_service_mgr.versioning import VersionFiles, write_bumped_version  # noqa: E402


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    files = VersionFiles(
        pyproject=ROOT / "pyproject.toml",
        package_init=ROOT / "src" / "my_service_mgr" / "__init__.py",
    )
    old_version, new_version = write_bumped_version(files)

    _run(["git", "add", str(files.pyproject), str(files.package_init)])
    _run(["git", "commit", "-m", f"Bump version to {new_version}"])
    _run(["git", "tag", "-a", f"v{new_version}", "-m", f"v{new_version}"])

    print(f"Bumped version {old_version} -> {new_version}")
    print(f"Created commit and tag v{new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

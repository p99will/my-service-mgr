#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def _version_files() -> VersionFiles:
    return VersionFiles(
        pyproject=ROOT / "pyproject.toml",
        package_init=ROOT / "src" / "my_service_mgr" / "__init__.py",
    )


def _bump_and_stage() -> tuple[str, str]:
    files = _version_files()
    old_version, new_version = write_bumped_version(files)
    _run(["git", "add", str(files.pyproject), str(files.package_init)])
    return old_version, new_version


def _tag_head_for_current_version() -> str:
    files = _version_files()
    current_version = read_bumped_version(files)
    tag_name = f"v{current_version}"
    existing_tag = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag_name}"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    points_at_head = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    if tag_name in points_at_head.stdout.splitlines():
        return tag_name
    if existing_tag.returncode == 0:
        print(f"Tag {tag_name} already exists and does not point at HEAD; leaving it unchanged.", file=sys.stderr)
        return tag_name
    _run(["git", "tag", "-a", tag_name, "-m", tag_name])
    return tag_name


def read_bumped_version(files: VersionFiles) -> str:
    from my_service_mgr.versioning import read_current_version

    return read_current_version(files.pyproject.read_text(encoding="utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bump and tag the project version.")
    parser.add_argument("--stage-only", action="store_true", help="Bump the version files and stage them.")
    parser.add_argument("--tag-head", action="store_true", help="Create the current version tag on HEAD if needed.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.stage_only and args.tag_head:
        print("Choose only one mode.", file=sys.stderr)
        return 2

    if args.stage_only:
        old_version, new_version = _bump_and_stage()
        print(f"Bumped version {old_version} -> {new_version}")
        print("Staged updated version files")
        return 0

    if args.tag_head:
        tag_name = _tag_head_for_current_version()
        print(f"Ensured tag {tag_name} points at HEAD")
        return 0

    old_version, new_version = _bump_and_stage()
    _run(["git", "commit", "-m", f"Bump version to {new_version}"])
    _run(["git", "tag", "-a", f"v{new_version}", "-m", f"v{new_version}"])

    print(f"Bumped version {old_version} -> {new_version}")
    print(f"Created commit and tag v{new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

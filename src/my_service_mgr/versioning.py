from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


VERSION_PATTERN = re.compile(r'^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$')


@dataclass(frozen=True)
class VersionFiles:
    pyproject: Path
    package_init: Path


def parse_version(value: str) -> tuple[int, int, int]:
    """Parse a strict semantic version in `X.Y.Z` form."""

    match = VERSION_PATTERN.match(value.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {value!r}")
    return (int(match.group("major")), int(match.group("minor")), int(match.group("patch")))


def bump_patch(value: str) -> str:
    """Increment only the patch component of a semantic version."""

    major, minor, patch = parse_version(value)
    return f"{major}.{minor}.{patch + 1}"


def update_version_text(text: str, old_version: str, new_version: str) -> str:
    """Update either supported version declaration in one file body."""

    updated = text.replace(f'version = "{old_version}"', f'version = "{new_version}"', 1)
    updated = updated.replace(f'__version__ = "{old_version}"', f'__version__ = "{new_version}"', 1)
    return updated


def read_current_version(pyproject_text: str) -> str:
    """Extract the canonical project version from `pyproject.toml`."""

    match = re.search(r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def write_bumped_version(files: VersionFiles) -> tuple[str, str]:
    """Bump the patch version in both tracked source files."""

    pyproject_text = files.pyproject.read_text(encoding="utf-8")
    old_version = read_current_version(pyproject_text)
    new_version = bump_patch(old_version)
    files.pyproject.write_text(update_version_text(pyproject_text, old_version, new_version), encoding="utf-8")

    init_text = files.package_init.read_text(encoding="utf-8")
    files.package_init.write_text(update_version_text(init_text, old_version, new_version), encoding="utf-8")
    return old_version, new_version

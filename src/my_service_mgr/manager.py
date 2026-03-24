from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_PATH_PLACEHOLDER = "__SCRIPT_PATH__"
DEFAULT_TEMPLATE_SCOPE = "auto"
SYSTEM_LIST_EXCLUDE_PREFIXES = ("systemd-",)
SYSTEM_LIST_EXCLUDE_UNITS = {
    "dbus.service",
    "emergency.service",
    "rescue.service",
}
ENABLED_STATES = {
    "enabled",
    "enabled-runtime",
    "linked",
    "linked-runtime",
    "static",
    "indirect",
    "alias",
    "generated",
    "transient",
}
ACTIVE_STATES = {
    "active",
    "activating",
    "reloading",
}


class ElevationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    unit_name: str
    action: str
    message: str
    error: str | None = None
    script_dest: str | None = None
    unit_dest: str | None = None
    expected_enabled: bool | None = None
    actual_enabled: str | None = None
    scope: str | None = None
    source: str = "template"


@dataclass(frozen=True)
class SystemdContext:
    scope: str
    unit_dir: Path
    bin_dir: Path
    systemctl_base: list[str]

    @property
    def is_user_mode(self) -> bool:
        return self.scope == "user"


@dataclass(frozen=True)
class ServiceTemplate:
    unit_template_path: Path
    scripts_dir: Path
    unit_install_dir: Path
    bin_install_dir: Path

    @property
    def unit_name(self) -> str:
        return self.unit_template_path.name

    @property
    def unit_stem(self) -> str:
        return self.unit_template_path.stem

    def resolve_script_template_path(self) -> Path:
        candidates = [
            self.scripts_dir / f"{self.unit_stem}.sh",
            self.scripts_dir / self.unit_stem,
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            f"Missing script template for unit '{self.unit_name}'. Tried: "
            + ", ".join(str(p) for p in candidates)
        )

    def installed_unit_path(self) -> Path:
        return self.unit_install_dir / self.unit_name

    def installed_script_path(self) -> Path:
        script_template = self.resolve_script_template_path()
        return self.bin_install_dir / script_template.name

    def render_unit_text(self, installed_script_path: Path) -> str:
        text = self.unit_template_path.read_text(encoding="utf-8")
        if SCRIPT_PATH_PLACEHOLDER not in text:
            raise ValueError(
                f"Unit template '{self.unit_template_path}' is missing placeholder "
                f"'{SCRIPT_PATH_PLACEHOLDER}'."
            )
        return text.replace(SCRIPT_PATH_PLACEHOLDER, str(installed_script_path))

    def description(self) -> str:
        text = self.unit_template_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"^Description\s*=\s*(.*?)\s*$", stripped)
            if match:
                return match.group(1) or ""
        return ""


def _default_log_path() -> Path:
    home = Path("~").expanduser()
    state_dir = home / ".local" / "state" / "my-service-mgr"
    log_dir = state_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "my-service-mgr.log"
    except Exception:
        return Path.cwd() / "my-service-mgr.log"


def _normalize_unit_name(unit_name: str) -> str:
    unit_name = unit_name.strip()
    if unit_name.endswith(".service"):
        return unit_name
    return f"{unit_name}.service"


def _default_template_scope(mode: str, dry_run: bool) -> str:
    is_root = os.geteuid() == 0
    if mode == "auto":
        return "system" if is_root else "user"
    if mode == "system":
        return "system"
    if mode == "user":
        return "user"
    raise ValueError(f"Unknown mode: {mode!r} (expected auto/system/user)")


def _context_for_scope(scope: str) -> SystemdContext:
    if scope == "system":
        return SystemdContext(
            scope="system",
            unit_dir=Path("/etc/systemd/system"),
            bin_dir=Path("/usr/local/bin"),
            systemctl_base=["systemctl"],
        )
    if scope == "user":
        return SystemdContext(
            scope="user",
            unit_dir=Path("~/.config/systemd/user").expanduser(),
            bin_dir=Path("~/.local/bin").expanduser(),
            systemctl_base=["systemctl", "--user"],
        )
    raise ValueError(f"Unknown scope: {scope!r} (expected user/system)")


def _run(
    systemctl_base: list[str],
    args: list[str],
    *,
    logger: logging.Logger,
    unit_name: str | None = None,
    use_sudo: bool = False,
) -> subprocess.CompletedProcess[str]:
    cmd = (["sudo"] if use_sudo else []) + systemctl_base + args
    start = time.time()
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    elapsed_ms = int((time.time() - start) * 1000)

    prefix = f"[{unit_name}] " if unit_name else ""
    if proc.returncode == 0:
        logger.info("%scommand ok: %s (elapsed=%sms)", prefix, " ".join(cmd), elapsed_ms)
    else:
        logger.error(
            "%scommand failed rc=%s: %s\nstdout:\n%s\nstderr:\n%s",
            prefix,
            proc.returncode,
            " ".join(cmd),
            (proc.stdout or "").strip(),
            (proc.stderr or "").strip(),
        )
    return proc


def _run_command(
    cmd: list[str],
    *,
    logger: logging.Logger,
    unit_name: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    start = time.time()
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True, input=input_text)
    elapsed_ms = int((time.time() - start) * 1000)

    prefix = f"[{unit_name}] " if unit_name else ""
    if proc.returncode == 0:
        logger.info("%scommand ok: %s (elapsed=%sms)", prefix, " ".join(cmd), elapsed_ms)
    else:
        logger.error(
            "%scommand failed rc=%s: %s\nstdout:\n%s\nstderr:\n%s",
            prefix,
            proc.returncode,
            " ".join(cmd),
            (proc.stdout or "").strip(),
            (proc.stderr or "").strip(),
        )
    return proc


def _parse_unit_files_output(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("UNIT FILE"):
            continue
        if stripped.startswith(tuple("0123456789")) and " unit files listed." in stripped:
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        unit_name, enabled_state = parts[0], parts[1]
        if not unit_name.endswith(".service"):
            continue
        rows[unit_name] = enabled_state
    return rows


def _parse_list_units_output(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped:
            continue
        parts = stripped.split(None, 4)
        if len(parts) < 4:
            continue
        unit_name = parts[0]
        if not unit_name.endswith(".service"):
            continue
        active = parts[2]
        description = parts[4] if len(parts) == 5 else ""
        rows[unit_name] = {
            "active": active,
            "description": description,
        }
    return rows


def _enabled_label(raw_state: str) -> str:
    if raw_state in ENABLED_STATES:
        return raw_state
    if raw_state in {"disabled", "masked"}:
        return raw_state
    return "unknown"


def _active_label(raw_state: str) -> str:
    if raw_state in ACTIVE_STATES or raw_state == "inactive":
        return raw_state
    if raw_state in {"failed", "deactivating"}:
        return raw_state
    return "unknown"


def _row_state(enabled: str, active: str) -> str:
    if enabled == "enabled":
        return "enabled"
    if active == "active":
        return "active"
    if enabled in {"disabled", "masked"}:
        return enabled
    if enabled != "unknown":
        return enabled
    return active


def _should_include_system_unit(unit_name: str, enabled: str, active: str) -> bool:
    if not unit_name.endswith(".service"):
        return False
    if unit_name in SYSTEM_LIST_EXCLUDE_UNITS:
        return False
    if unit_name.startswith(SYSTEM_LIST_EXCLUDE_PREFIXES):
        return False
    return enabled in ENABLED_STATES or active in ACTIVE_STATES


def _past_tense(action: str) -> str:
    if action == "start":
        return "Started"
    if action == "stop":
        return "Stopped"
    if action == "restart":
        return "Restarted"
    if action == "enable":
        return "Enabled"
    if action == "disable":
        return "Disabled"
    return action.capitalize()


class ServiceManager:
    def __init__(
        self,
        services_dir: Path,
        scripts_dir: Path,
        *,
        mode: str = DEFAULT_TEMPLATE_SCOPE,
        dry_run: bool = False,
    ) -> None:
        self.services_dir = services_dir
        self.scripts_dir = scripts_dir
        self.dry_run = dry_run
        self.template_scope = _default_template_scope(mode=mode, dry_run=dry_run)
        self.contexts = {
            "system": _context_for_scope("system"),
            "user": _context_for_scope("user"),
        }

        self.log_path = _default_log_path()
        self.logger = logging.getLogger("my_service_mgr")
        self.logger.setLevel(logging.INFO)
        if not any(
            isinstance(handler, logging.FileHandler)
            and getattr(handler, "baseFilename", "").endswith(str(self.log_path))
            for handler in self.logger.handlers
        ):
            try:
                file_handler = logging.FileHandler(self.log_path, encoding="utf-8")
            except OSError:
                self.log_path = Path.cwd() / "my-service-mgr.log"
                file_handler = logging.FileHandler(self.log_path, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(file_handler)

        self.logger.info(
            "Initialized manager template_scope=%s dry_run=%s log=%s",
            self.template_scope,
            dry_run,
            str(self.log_path),
        )

    def _ctx(self, scope: str | None) -> SystemdContext:
        selected_scope = scope or self.template_scope
        return self.contexts[selected_scope]

    def _use_sudo(self, scope: str) -> bool:
        return scope == "system" and os.geteuid() != 0 and not self.dry_run

    def needs_elevation(self, scope: str) -> bool:
        return self._use_sudo(scope)

    def ensure_elevation(self, scope: str) -> None:
        if not self._use_sudo(scope):
            return
        subprocess.run(["sudo", "-v"], check=True, text=True)

    def _snapshot_row(self, unit_name: str, *, scope: str, source: str) -> dict[str, str] | None:
        try:
            if source == "existing":
                return self.get_existing_service(unit_name, scope)
            state, enabled, active = self._installed_state(unit_name, scope=scope)
            return {
                "unit_name": unit_name,
                "state": state,
                "enabled": enabled,
                "active": active,
                "scope": scope,
                "source": source,
            }
        except Exception:
            self.logger.exception("snapshot failed for unit=%s scope=%s source=%s", unit_name, scope, source)
            return None

    def _log_action_event(
        self,
        result: ActionResult,
        *,
        before: dict[str, str] | None,
        after: dict[str, str] | None,
        command: str | None = None,
    ) -> None:
        before_enabled = before["enabled"] if before else "unknown"
        before_active = before["active"] if before else "unknown"
        after_enabled = after["enabled"] if after else "unknown"
        after_active = after["active"] if after else "unknown"
        self.logger.info(
            "service_event time=%s ok=%s source=%s scope=%s action=%s unit=%s before_enabled=%s before_active=%s after_enabled=%s after_active=%s command=%s message=%s",
            datetime.now(timezone.utc).isoformat(),
            result.ok,
            result.source,
            result.scope or "",
            result.action,
            result.unit_name,
            before_enabled,
            before_active,
            after_enabled,
            after_active,
            command or "",
            result.message,
        )

    def _ensure_dir(self, path: Path, *, ctx: SystemdContext, unit_name: str) -> None:
        if self._use_sudo(ctx.scope):
            proc = _run_command(["sudo", "mkdir", "-p", str(path)], logger=self.logger, unit_name=unit_name)
            if proc.returncode != 0:
                err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown error"
                raise RuntimeError(f"Failed to create directory {path}: {err}")
            return
        path.mkdir(parents=True, exist_ok=True)

    def _install_template_file(
        self,
        *,
        source_path: Path | None,
        content: str | None,
        dest_path: Path,
        mode: int,
        ctx: SystemdContext,
        unit_name: str,
    ) -> None:
        if self._use_sudo(ctx.scope):
            if source_path is not None:
                proc = _run_command(
                    ["sudo", "install", "-D", "-m", f"{mode:o}", str(source_path), str(dest_path)],
                    logger=self.logger,
                    unit_name=unit_name,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown error"
                    raise RuntimeError(f"Failed to install {dest_path}: {err}")
                return

            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write(content or "")
                temp_path = Path(handle.name)
            try:
                proc = _run_command(
                    ["sudo", "install", "-D", "-m", f"{mode:o}", str(temp_path), str(dest_path)],
                    logger=self.logger,
                    unit_name=unit_name,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown error"
                    raise RuntimeError(f"Failed to install {dest_path}: {err}")
            finally:
                temp_path.unlink(missing_ok=True)
            return

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path is not None:
            shutil.copy2(source_path, dest_path)
            dest_path.chmod(mode)
            return
        dest_path.write_text(content or "", encoding="utf-8")
        dest_path.chmod(mode)

    def _remove_path(self, path: Path, *, ctx: SystemdContext, unit_name: str) -> None:
        if self._use_sudo(ctx.scope):
            proc = _run_command(["sudo", "rm", "-f", str(path)], logger=self.logger, unit_name=unit_name)
            if proc.returncode != 0:
                err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown error"
                raise RuntimeError(f"Failed to remove {path}: {err}")
            return
        if path.exists():
            path.unlink()

    def _ensure_template_dirs(self) -> None:
        if not self.services_dir.exists():
            raise FileNotFoundError(f"Services directory does not exist: {self.services_dir}")
        if not self.scripts_dir.exists():
            raise FileNotFoundError(f"Scripts directory does not exist: {self.scripts_dir}")

    def discover_service_templates(self, scope: str | None = None) -> list[ServiceTemplate]:
        self._ensure_template_dirs()
        ctx = self._ctx(scope)
        templates: list[ServiceTemplate] = []
        for path in sorted(self.services_dir.glob("*.service")):
            templates.append(
                ServiceTemplate(
                    unit_template_path=path,
                    scripts_dir=self.scripts_dir,
                    unit_install_dir=ctx.unit_dir,
                    bin_install_dir=ctx.bin_dir,
                )
            )
        return templates

    def _installed_state(self, unit_name: str, *, scope: str | None = None) -> tuple[str, str, str]:
        ctx = self._ctx(scope)
        unit_path = ctx.unit_dir / unit_name
        if not unit_path.exists():
            return ("disabled", "disabled", "inactive")

        enabled_proc = _run(ctx.systemctl_base, ["is-enabled", unit_name], logger=self.logger, unit_name=unit_name)
        enabled = _enabled_label((enabled_proc.stdout or "").strip())

        active_proc = _run(ctx.systemctl_base, ["is-active", unit_name], logger=self.logger, unit_name=unit_name)
        active = _active_label((active_proc.stdout or "").strip())

        if enabled == "unknown":
            return ("unknown", "unknown", active)
        return (_row_state(enabled, active), enabled, active)

    def list_service_templates_with_status(self, scope: str | None = None) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for template in self.discover_service_templates(scope=scope):
            row_scope = scope or self.template_scope
            state, enabled, active = self._installed_state(template.unit_name, scope=row_scope)
            rows.append(
                {
                    "unit_name": template.unit_name,
                    "description": template.description(),
                    "state": state,
                    "enabled": enabled,
                    "active": active,
                    "source": "template",
                    "scope": row_scope,
                }
            )
        return rows

    def list_existing_services(self, scope: str, *, filtered: bool = True) -> list[dict[str, str]]:
        ctx = self._ctx(scope)
        unit_files_proc = _run(
            ctx.systemctl_base,
            ["list-unit-files", "--type=service", "--no-legend", "--no-pager"],
            logger=self.logger,
        )
        active_proc = _run(
            ctx.systemctl_base,
            ["list-units", "--type=service", "--all", "--no-legend", "--no-pager"],
            logger=self.logger,
        )

        unit_files = _parse_unit_files_output(unit_files_proc.stdout or "")
        active_rows = _parse_list_units_output(active_proc.stdout or "")
        unit_names = sorted(set(unit_files) | set(active_rows))

        rows: list[dict[str, str]] = []
        for unit_name in unit_names:
            enabled = _enabled_label(unit_files.get(unit_name, "unknown"))
            active = _active_label(active_rows.get(unit_name, {}).get("active", "inactive"))
            description = active_rows.get(unit_name, {}).get("description", "")
            if scope == "system" and filtered and not _should_include_system_unit(unit_name, enabled, active):
                continue
            rows.append(
                {
                    "unit_name": unit_name,
                    "description": description,
                    "state": _row_state(enabled, active),
                    "enabled": enabled,
                    "active": active,
                    "source": "existing",
                    "scope": scope,
                }
            )
        return rows

    def get_existing_service(self, unit_name: str, scope: str) -> dict[str, str]:
        ctx = self._ctx(scope)
        unit_name = _normalize_unit_name(unit_name)

        enabled_proc = _run(ctx.systemctl_base, ["is-enabled", unit_name], logger=self.logger, unit_name=unit_name)
        active_proc = _run(ctx.systemctl_base, ["is-active", unit_name], logger=self.logger, unit_name=unit_name)
        desc_proc = _run(
            ctx.systemctl_base,
            ["show", unit_name, "--property=Description", "--value"],
            logger=self.logger,
            unit_name=unit_name,
        )

        enabled = _enabled_label((enabled_proc.stdout or "").strip())
        active = _active_label((active_proc.stdout or "").strip())
        description = (desc_proc.stdout or "").strip()
        return {
            "unit_name": unit_name,
            "description": description,
            "state": _row_state(enabled, active),
            "enabled": enabled,
            "active": active,
            "source": "existing",
            "scope": scope,
        }

    def enable_by_unit_name(self, unit_name: str) -> ActionResult:
        template = self._get_template(unit_name, scope=self.template_scope)
        return self._install(template, self._ctx(self.template_scope))

    def disable_by_unit_name(self, unit_name: str) -> ActionResult:
        template = self._get_template(unit_name, scope=self.template_scope)
        return self._uninstall(template, self._ctx(self.template_scope))

    def enable_existing_unit(self, unit_name: str, scope: str) -> ActionResult:
        return self._existing_action(unit_name, "enable", ["enable", "--now", _normalize_unit_name(unit_name)], scope)

    def disable_existing_unit(self, unit_name: str, scope: str) -> ActionResult:
        return self._existing_action(unit_name, "disable", ["disable", "--now", _normalize_unit_name(unit_name)], scope)

    def start_existing_unit(self, unit_name: str, scope: str) -> ActionResult:
        return self._existing_action(unit_name, "start", ["start", _normalize_unit_name(unit_name)], scope)

    def stop_existing_unit(self, unit_name: str, scope: str) -> ActionResult:
        return self._existing_action(unit_name, "stop", ["stop", _normalize_unit_name(unit_name)], scope)

    def restart_existing_unit(self, unit_name: str, scope: str) -> ActionResult:
        return self._existing_action(unit_name, "restart", ["restart", _normalize_unit_name(unit_name)], scope)

    def status_existing_unit(self, unit_name: str, scope: str) -> ActionResult:
        row = self.get_existing_service(unit_name, scope)
        msg = (
            f"{row['unit_name']} [{scope}] enabled={row['enabled']} "
            f"active={row['active']} state={row['state']}"
        )
        if row["description"]:
            msg = f"{msg} description={row['description']}"
        return ActionResult(
            ok=True,
            unit_name=row["unit_name"],
            action="status",
            message=msg,
            actual_enabled=row["enabled"],
            scope=scope,
            source="existing",
        )

    def _get_template(self, unit_name: str, *, scope: str) -> ServiceTemplate:
        self._ensure_template_dirs()
        unit_name = _normalize_unit_name(unit_name)
        path = self.services_dir / unit_name
        if not path.exists():
            raise FileNotFoundError(f"Unknown service template: {path}")
        ctx = self._ctx(scope)
        return ServiceTemplate(
            unit_template_path=path,
            scripts_dir=self.scripts_dir,
            unit_install_dir=ctx.unit_dir,
            bin_install_dir=ctx.bin_dir,
        )

    def _install(self, template: ServiceTemplate, ctx: SystemdContext) -> ActionResult:
        action = "enable"
        unit_name = template.unit_name
        installed_script_path = template.installed_script_path()
        installed_unit_path = template.installed_unit_path()
        before = self._snapshot_row(unit_name, scope=ctx.scope, source="template")

        if self.dry_run:
            msg = (
                f"[dry-run] Would install script to {installed_script_path} and unit to {installed_unit_path} "
                f"then run: {' '.join(ctx.systemctl_base)} enable --now {unit_name} (log: {self.log_path.name})"
            )
            self.logger.info("%s", msg)
            result = ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=str(installed_script_path),
                unit_dest=str(installed_unit_path),
                expected_enabled=True,
                actual_enabled="unknown",
                scope=ctx.scope,
                source="template",
            )
            self._log_action_event(result, before=before, after=None, command=f"{' '.join(ctx.systemctl_base)} enable --now {unit_name}")
            return result

        script_dest = str(installed_script_path)
        unit_dest = str(installed_unit_path)
        self.logger.info("[%s] install paths script=%s unit=%s scope=%s", unit_name, script_dest, unit_dest, ctx.scope)

        try:
            self._ensure_dir(installed_script_path.parent, ctx=ctx, unit_name=unit_name)
            self._install_template_file(
                source_path=template.resolve_script_template_path(),
                content=None,
                dest_path=installed_script_path,
                mode=0o755,
                ctx=ctx,
                unit_name=unit_name,
            )

            self._ensure_dir(ctx.unit_dir, ctx=ctx, unit_name=unit_name)
            rendered = template.render_unit_text(installed_script_path=installed_script_path)
            self._install_template_file(
                source_path=None,
                content=rendered,
                dest_path=installed_unit_path,
                mode=0o644,
                ctx=ctx,
                unit_name=unit_name,
            )

            _run(
                ctx.systemctl_base,
                ["daemon-reload"],
                logger=self.logger,
                unit_name=unit_name,
                use_sudo=self._use_sudo(ctx.scope),
            )
            enable_proc = _run(
                ctx.systemctl_base,
                ["enable", "--now", unit_name],
                logger=self.logger,
                unit_name=unit_name,
                use_sudo=self._use_sudo(ctx.scope),
            )
            if enable_proc.returncode != 0:
                err = (enable_proc.stderr or "").strip() or (enable_proc.stdout or "").strip() or "unknown error"
                return ActionResult(
                    ok=False,
                    unit_name=unit_name,
                    action=action,
                    message=(
                        f"Error: Failed to enable/start {unit_name} "
                        f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                    ),
                    error=err,
                    script_dest=script_dest,
                    unit_dest=unit_dest,
                    expected_enabled=True,
                    actual_enabled=None,
                    scope=ctx.scope,
                    source="template",
                )

            _, enabled, _ = self._installed_state(unit_name, scope=ctx.scope)
            if enabled != "enabled":
                result = ActionResult(
                    ok=False,
                    unit_name=unit_name,
                    action=action,
                    message=(
                        f"Error: {unit_name} enabled check failed (expected enabled, got {enabled}) "
                        f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                    ),
                    error=f"systemctl is-enabled returned: {enabled}",
                    script_dest=script_dest,
                    unit_dest=unit_dest,
                    expected_enabled=True,
                    actual_enabled=enabled,
                    scope=ctx.scope,
                    source="template",
                )
                self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=ctx.scope, source="template"), command=f"{' '.join(ctx.systemctl_base)} enable --now {unit_name}")
                return result

            msg = (
                f"Enabled {unit_name}. Copied script to {script_dest} and unit to {unit_dest}. "
                f"(scope: {ctx.scope}, log: {self.log_path.name})"
            )
            self.logger.info("%s", msg)
            result = ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=script_dest,
                unit_dest=unit_dest,
                expected_enabled=True,
                actual_enabled=enabled,
                scope=ctx.scope,
                source="template",
            )
            self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=ctx.scope, source="template"), command=f"{' '.join(ctx.systemctl_base)} enable --now {unit_name}")
            return result
        except ElevationRequired:
            raise
        except Exception as exc:
            self.logger.exception("install exception for %s", unit_name)
            result = ActionResult(
                ok=False,
                unit_name=unit_name,
                action=action,
                message=(
                    f"Error: Exception while enabling {unit_name} "
                    f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                ),
                error=str(exc),
                script_dest=script_dest,
                unit_dest=unit_dest,
                expected_enabled=True,
                scope=ctx.scope,
                source="template",
            )
            self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=ctx.scope, source="template"), command=f"{' '.join(ctx.systemctl_base)} enable --now {unit_name}")
            return result

    def _uninstall(self, template: ServiceTemplate, ctx: SystemdContext) -> ActionResult:
        action = "disable"
        unit_name = template.unit_name
        installed_script_path = template.installed_script_path()
        installed_unit_path = template.installed_unit_path()
        before = self._snapshot_row(unit_name, scope=ctx.scope, source="template")

        if self.dry_run:
            msg = (
                f"[dry-run] Would disable/remove unit {installed_unit_path} "
                f"and run: {' '.join(ctx.systemctl_base)} disable --now {unit_name} "
                f"then remove script {installed_script_path} (log: {self.log_path.name})"
            )
            self.logger.info("%s", msg)
            result = ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=str(installed_script_path),
                unit_dest=str(installed_unit_path),
                expected_enabled=False,
                actual_enabled="unknown",
                scope=ctx.scope,
                source="template",
            )
            self._log_action_event(result, before=before, after=None, command=f"{' '.join(ctx.systemctl_base)} disable --now {unit_name}")
            return result

        script_dest = str(installed_script_path)
        unit_dest = str(installed_unit_path)
        self.logger.info("[%s] uninstall paths script=%s unit=%s scope=%s", unit_name, script_dest, unit_dest, ctx.scope)

        try:
            _run(
                ctx.systemctl_base,
                ["disable", "--now", unit_name],
                logger=self.logger,
                unit_name=unit_name,
                use_sudo=self._use_sudo(ctx.scope),
            )
            self._remove_path(installed_unit_path, ctx=ctx, unit_name=unit_name)

            _run(
                ctx.systemctl_base,
                ["daemon-reload"],
                logger=self.logger,
                unit_name=unit_name,
                use_sudo=self._use_sudo(ctx.scope),
            )
            self._remove_path(installed_script_path, ctx=ctx, unit_name=unit_name)

            _, enabled, _ = self._installed_state(unit_name, scope=ctx.scope)
            if enabled == "enabled":
                result = ActionResult(
                    ok=False,
                    unit_name=unit_name,
                    action=action,
                    message=(
                        f"Error: {unit_name} still appears enabled after disable "
                        f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                    ),
                    error=f"systemctl is-enabled returned: {enabled}",
                    script_dest=script_dest,
                    unit_dest=unit_dest,
                    expected_enabled=False,
                    actual_enabled=enabled,
                    scope=ctx.scope,
                    source="template",
                )
                self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=ctx.scope, source="template"), command=f"{' '.join(ctx.systemctl_base)} disable --now {unit_name}")
                return result

            msg = (
                f"Disabled {unit_name}. Removed script {script_dest} and unit {unit_dest}. "
                f"(scope: {ctx.scope}, log: {self.log_path.name})"
            )
            self.logger.info("%s", msg)
            result = ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=script_dest,
                unit_dest=unit_dest,
                expected_enabled=False,
                actual_enabled=enabled,
                scope=ctx.scope,
                source="template",
            )
            self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=ctx.scope, source="template"), command=f"{' '.join(ctx.systemctl_base)} disable --now {unit_name}")
            return result
        except Exception as exc:
            self.logger.exception("uninstall exception for %s", unit_name)
            result = ActionResult(
                ok=False,
                unit_name=unit_name,
                action=action,
                message=(
                    f"Error: Exception while disabling {unit_name} "
                    f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                ),
                error=str(exc),
                script_dest=str(installed_script_path),
                unit_dest=str(installed_unit_path),
                expected_enabled=False,
                scope=ctx.scope,
                source="template",
            )
            self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=ctx.scope, source="template"), command=f"{' '.join(ctx.systemctl_base)} disable --now {unit_name}")
            return result

    def _existing_action(self, unit_name: str, action: str, args: list[str], scope: str) -> ActionResult:
        ctx = self._ctx(scope)
        unit_name = _normalize_unit_name(unit_name)
        command_display = " ".join(ctx.systemctl_base + args)
        before = self._snapshot_row(unit_name, scope=scope, source="existing")

        if self.dry_run:
            msg = f"[dry-run] Would run: {command_display} (log: {self.log_path.name})"
            self.logger.info("%s", msg)
            result = ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                actual_enabled="unknown",
                scope=scope,
                source="existing",
            )
            self._log_action_event(result, before=before, after=None, command=command_display)
            return result

        proc = _run(
            ctx.systemctl_base,
            args,
            logger=self.logger,
            unit_name=unit_name,
            use_sudo=self._use_sudo(scope),
        )
        if proc.returncode != 0:
            err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown error"
            result = ActionResult(
                ok=False,
                unit_name=unit_name,
                action=action,
                message=f"Error: Failed to {action} {unit_name} in {scope} scope. (log: {self.log_path.name})",
                error=err,
                actual_enabled=None,
                scope=scope,
                source="existing",
            )
            self._log_action_event(result, before=before, after=self._snapshot_row(unit_name, scope=scope, source="existing"), command=command_display)
            return result

        row = self.get_existing_service(unit_name, scope)
        msg = f"{_past_tense(action)} {unit_name} in {scope} scope. enabled={row['enabled']} active={row['active']} (log: {self.log_path.name})"
        result = ActionResult(
            ok=True,
            unit_name=unit_name,
            action=action,
            message=msg,
            actual_enabled=row["enabled"],
            scope=scope,
            source="existing",
        )
        self._log_action_event(result, before=before, after=row, command=command_display)
        return result

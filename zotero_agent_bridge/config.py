from __future__ import annotations

import json
import os
import platform
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime_paths import resource_path
from .utils import ensure_dir, read_json


def _default_zotero_data_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    if platform.system() == "Windows":
        return home / "Zotero"
    return home / "Zotero"


def _load_config_file() -> dict[str, Any]:
    config_env = os.environ.get("ZOTERO_AGENT_BRIDGE_CONFIG")
    candidates = [Path(config_env)] if config_env else [Path.cwd() / "zotero_agent_bridge.json"]
    for candidate in candidates:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8-sig"))
    return {}


@dataclass(slots=True)
class PiSettings:
    executable: str = "pi"
    session_dir: Path | None = None
    cwd_mode: str = "selected_pdf_directory"
    system_prompt_path: Path | None = None
    model: str | None = None
    thinking_level: str = "medium"
    idle_timeout_seconds: float = 1800.0
    max_context_chars: int = 500_000
    poll_interval_ms: int = 300
    note_title_timeout_seconds: float = 20.0
    experience_timeout_enabled: bool = False
    experience_call_timeout_seconds: float = 600.0
    experience_total_timeout_seconds: float = 900.0
    experience_chunk_chars: int = 100_000
    experience_extraction_chunk_chars: int = 100_000
    experience_structure_max_chars: int = 250_000
    experience_cross_link_max_calls: int = 8
    experience_coverage_audit: bool = True
    experience_json_repair_attempts: int = 1

    def validate(self) -> None:
        if self.cwd_mode != "selected_pdf_directory":
            raise ValueError(f"Unsupported Pi cwd_mode: {self.cwd_mode}")
        if self.thinking_level not in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"Unsupported Pi thinking_level: {self.thinking_level}")
        if self.idle_timeout_seconds <= 0:
            raise ValueError("Pi idle_timeout_seconds must be positive")
        if self.max_context_chars <= 0:
            raise ValueError("Pi max_context_chars must be positive")
        if self.poll_interval_ms < 100:
            raise ValueError("Pi poll_interval_ms must be at least 100")
        if self.note_title_timeout_seconds <= 0:
            raise ValueError("Pi note_title_timeout_seconds must be positive")
        if self.experience_call_timeout_seconds <= 0:
            raise ValueError("Pi experience_call_timeout_seconds must be positive")
        if self.experience_total_timeout_seconds < self.experience_call_timeout_seconds:
            raise ValueError("Pi experience_total_timeout_seconds must cover at least one generation call")
        if self.experience_chunk_chars < 10_000:
            raise ValueError("Pi experience_chunk_chars must be at least 10000")
        if self.experience_extraction_chunk_chars < 10_000:
            raise ValueError("Pi experience_extraction_chunk_chars must be at least 10000")
        if self.experience_structure_max_chars < 10_000:
            raise ValueError("Pi experience_structure_max_chars must be at least 10000")
        if not 0 <= self.experience_cross_link_max_calls <= 64:
            raise ValueError("Pi experience_cross_link_max_calls must be between 0 and 64")
        if self.experience_json_repair_attempts not in {0, 1}:
            raise ValueError("Pi experience_json_repair_attempts must be 0 or 1")


@dataclass(slots=True)
class Settings:
    host: str
    port: int
    api_token: str
    zotero_local_api_base: str
    bridge_home: Path
    addon_timeout_seconds: float
    addon_status_ttl_seconds: float
    user_agent: str
    base_attachment_path: Path | None = None
    pi: PiSettings | None = None
    lifecycle_owner_id: str | None = None
    lifecycle_owner_token: str | None = None
    lifecycle_addon_exit_grace_seconds: float = 30.0
    lifecycle_watchdog_interval_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "Settings":
        config = _load_config_file()
        pi_config = config.get("pi") or {}
        data_dir = Path(
            os.environ.get("ZOTERO_DATA_DIR")
            or config.get("zotero_data_dir")
            or _default_zotero_data_dir()
        )
        bridge_home = Path(
            os.environ.get("ZOTERO_AGENT_BRIDGE_HOME")
            or config.get("bridge_home")
            or data_dir / "zotero-agent-bridge"
        )
        base_attachment = (
            os.environ.get("ZOTERO_AGENT_BRIDGE_BASE_ATTACHMENT_PATH")
            or config.get("base_attachment_path")
        )
        pi_session_dir = (
            os.environ.get("ZOTERO_AGENT_BRIDGE_PI_SESSION_DIR")
            or pi_config.get("session_dir")
        )
        pi_system_prompt_path = (
            os.environ.get("ZOTERO_AGENT_BRIDGE_PI_SYSTEM_PROMPT_PATH")
            or pi_config.get("system_prompt_path")
        )
        settings = cls(
            host=os.environ.get("ZOTERO_AGENT_BRIDGE_HOST") or config.get("host") or "127.0.0.1",
            port=int(os.environ.get("ZOTERO_AGENT_BRIDGE_PORT") or config.get("port") or 8765),
            api_token=os.environ.get("ZOTERO_AGENT_BRIDGE_TOKEN") or config.get("api_token") or "",
            zotero_local_api_base=(
                os.environ.get("ZOTERO_AGENT_BRIDGE_LOCAL_API_BASE")
                or config.get("zotero_local_api_base")
                or "http://127.0.0.1:23119/api/users/0"
            ),
            bridge_home=bridge_home,
            addon_timeout_seconds=float(
                os.environ.get("ZOTERO_AGENT_BRIDGE_ADDON_TIMEOUT")
                or config.get("addon_timeout_seconds")
                or 30.0
            ),
            addon_status_ttl_seconds=float(
                os.environ.get("ZOTERO_AGENT_BRIDGE_ADDON_STATUS_TTL")
                or config.get("addon_status_ttl_seconds")
                or 15.0
            ),
            user_agent=config.get("user_agent") or "ZoteroPiAssistant/0.4.2-beta",
            base_attachment_path=Path(base_attachment) if base_attachment else None,
            pi=PiSettings(
                executable=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXECUTABLE")
                    or pi_config.get("executable")
                    or "pi"
                ),
                session_dir=Path(pi_session_dir) if pi_session_dir else None,
                cwd_mode=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_CWD_MODE")
                    or pi_config.get("cwd_mode")
                    or "selected_pdf_directory"
                ),
                system_prompt_path=Path(pi_system_prompt_path) if pi_system_prompt_path else None,
                model=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_MODEL")
                    or pi_config.get("model")
                ),
                thinking_level=(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_THINKING_LEVEL")
                    or pi_config.get("thinking_level")
                    or "medium"
                ),
                idle_timeout_seconds=float(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_IDLE_TIMEOUT")
                    or pi_config.get("idle_timeout_seconds")
                    or 1800.0
                ),
                max_context_chars=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_MAX_CONTEXT_CHARS")
                    or pi_config.get("max_context_chars")
                    or 500_000
                ),
                poll_interval_ms=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_POLL_INTERVAL_MS")
                    or pi_config.get("poll_interval_ms")
                    or 300
                ),
                note_title_timeout_seconds=float(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_NOTE_TITLE_TIMEOUT")
                    or pi_config.get("note_title_timeout_seconds")
                    or 20.0
                ),
                experience_timeout_enabled=str(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_TIMEOUT_ENABLED")
                    if os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_TIMEOUT_ENABLED") is not None
                    else pi_config.get("experience_timeout_enabled", False)
                ).strip().lower() in {"1", "true", "yes", "on"},
                experience_call_timeout_seconds=float(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_CALL_TIMEOUT")
                    or pi_config.get("experience_call_timeout_seconds")
                    or 600.0
                ),
                experience_total_timeout_seconds=float(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_TOTAL_TIMEOUT")
                    or pi_config.get("experience_total_timeout_seconds")
                    or 900.0
                ),
                experience_chunk_chars=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_CHUNK_CHARS")
                    or pi_config.get("experience_chunk_chars")
                    or 100_000
                ),
                experience_extraction_chunk_chars=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_EXTRACTION_CHUNK_CHARS")
                    or pi_config.get("experience_extraction_chunk_chars")
                    or pi_config.get("experience_chunk_chars")
                    or 100_000
                ),
                experience_structure_max_chars=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_STRUCTURE_MAX_CHARS")
                    or pi_config.get("experience_structure_max_chars")
                    or 250_000
                ),
                experience_cross_link_max_calls=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_CROSS_LINK_MAX_CALLS")
                    if os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_CROSS_LINK_MAX_CALLS") is not None
                    else pi_config.get("experience_cross_link_max_calls", 8)
                ),
                experience_coverage_audit=str(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_COVERAGE_AUDIT")
                    if os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_COVERAGE_AUDIT") is not None
                    else pi_config.get("experience_coverage_audit", True)
                ).strip().lower() not in {"0", "false", "no", "off"},
                experience_json_repair_attempts=int(
                    os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_JSON_REPAIR_ATTEMPTS")
                    if os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_JSON_REPAIR_ATTEMPTS") is not None
                    else pi_config.get("experience_json_repair_attempts", 1)
                ),
            ),
            lifecycle_owner_id=(
                os.environ.get("ZOTERO_AGENT_BRIDGE_OWNER_ID")
                or config.get("lifecycle_owner_id")
            ),
            lifecycle_owner_token=(
                os.environ.get("ZOTERO_AGENT_BRIDGE_OWNER_TOKEN")
                or config.get("lifecycle_owner_token")
            ),
            lifecycle_addon_exit_grace_seconds=float(
                os.environ.get("ZOTERO_AGENT_BRIDGE_ADDON_EXIT_GRACE_SECONDS")
                or config.get("lifecycle_addon_exit_grace_seconds")
                or 30.0
            ),
            lifecycle_watchdog_interval_seconds=float(
                os.environ.get("ZOTERO_AGENT_BRIDGE_WATCHDOG_INTERVAL_SECONDS")
                or config.get("lifecycle_watchdog_interval_seconds")
                or 1.0
            ),
        )
        settings.prepare_runtime()
        return settings

    @property
    def commands_dir(self) -> Path:
        return self.bridge_home / "commands"

    @property
    def responses_dir(self) -> Path:
        return self.bridge_home / "responses"

    @property
    def archive_dir(self) -> Path:
        return self.bridge_home / "archive"

    @property
    def logs_dir(self) -> Path:
        return self.bridge_home / "logs"

    @property
    def status_dir(self) -> Path:
        return self.bridge_home / "status"

    @property
    def addon_status_path(self) -> Path:
        return self.status_dir / "addon-status.json"

    @property
    def operations_log_path(self) -> Path:
        return self.logs_dir / "operations.jsonl"

    @property
    def generated_config_path(self) -> Path:
        return self.bridge_home / "bridge.generated.json"

    def prepare_runtime(self) -> None:
        if self.lifecycle_addon_exit_grace_seconds <= 0:
            raise ValueError("lifecycle_addon_exit_grace_seconds must be positive")
        if self.lifecycle_watchdog_interval_seconds <= 0:
            raise ValueError("lifecycle_watchdog_interval_seconds must be positive")
        if bool(self.lifecycle_owner_id) != bool(self.lifecycle_owner_token):
            raise ValueError("lifecycle owner id and token must be configured together")
        if self.pi:
            if self.pi.session_dir is None:
                self.pi.session_dir = self.bridge_home / "pi-sessions"
            if self.pi.system_prompt_path is None:
                self.pi.system_prompt_path = resource_path("config", "literature-assistant.md")
            self.pi.validate()
        for directory in [
            self.bridge_home,
            self.commands_dir,
            self.responses_dir,
            self.archive_dir,
            self.logs_dir,
            self.status_dir,
            *([self.pi.session_dir] if self.pi and self.pi.session_dir else []),
        ]:
            ensure_dir(directory)
        if not self.api_token:
            persisted = read_json(self.generated_config_path, default={})
            token = persisted.get("api_token")
            if not token:
                token = secrets.token_hex(24)
                self.generated_config_path.write_text(
                    json.dumps({"api_token": token}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            self.api_token = token
        else:
            persisted = read_json(self.generated_config_path, default={})
            if persisted.get("api_token") != self.api_token:
                self.generated_config_path.write_text(
                    json.dumps({"api_token": self.api_token}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

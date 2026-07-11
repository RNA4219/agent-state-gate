"""Validated runtime configuration for agent-state-gate 0.5."""

from __future__ import annotations

import os
import re
import warnings
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

_ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}$")


class RuntimeProfile(StrEnum):
    LOCAL_ADVISORY = "local_advisory"
    CI_CONTRACT = "ci_contract"
    STAGING_ENFORCE = "staging_enforce"
    PRODUCTION_SHADOW = "production_shadow"
    PRODUCTION_ENFORCE = "production_enforce"

    @property
    def is_production(self) -> bool:
        return self in {
            RuntimeProfile.PRODUCTION_SHADOW,
            RuntimeProfile.PRODUCTION_ENFORCE,
        }


class FailurePolicyName(StrEnum):
    FAIL_CLOSED = "fail-closed"
    FAIL_OPEN = "fail-open"
    NEEDS_APPROVAL = "needs-approval"
    STALE_BLOCKED = "stale-blocked"


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AdapterConfigBase(_ConfigModel):
    enabled: bool = True
    timeout_ms: int = Field(default=5000, ge=1, le=300_000)
    failure_policy: FailurePolicyName = FailurePolicyName.FAIL_CLOSED

    _legacy_aliases: ClassVar[dict[str, str]] = {
        "timeout_seconds": "timeout_ms",
    }

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        for old, new in cls._legacy_aliases.items():
            if old not in data or new in data:
                continue
            converted = data.pop(old)
            if old == "timeout_seconds":
                converted = int(converted) * 1000
            warnings.warn(
                f"Configuration key '{old}' is deprecated; use '{new}'.",
                DeprecationWarning,
                stacklevel=3,
            )
            data[new] = converted
        return data

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000


class HTTPAdapterConfig(AdapterConfigBase):
    endpoint: str | None
    api_key: SecretStr | None = None

    _legacy_aliases: ClassVar[dict[str, str]] = {
        **AdapterConfigBase._legacy_aliases,
        "base_url": "endpoint",
    }

    @property
    def base_url(self) -> str | None:
        return self.endpoint


class GatefieldConfig(HTTPAdapterConfig):
    endpoint: str = "http://localhost:8080"


class ShipyardConfig(HTTPAdapterConfig):
    endpoint: str | None = "http://localhost:3000"
    jwt_token: SecretStr | None = None


class MemxConfig(AdapterConfigBase):
    endpoint: str | None = None
    command: str | None = None
    api_key: SecretStr | None = None
    use_http: bool = True
    timeout_ms: int = 3000
    failure_policy: FailurePolicyName = FailurePolicyName.STALE_BLOCKED

    _legacy_aliases: ClassVar[dict[str, str]] = {
        **AdapterConfigBase._legacy_aliases,
        "base_url": "endpoint",
        "cli_path": "command",
    }

    @property
    def base_url(self) -> str | None:
        return self.endpoint

    @property
    def cli_path(self) -> str | None:
        return self.command


class TaskstateConfig(AdapterConfigBase):
    command: str = "agent-taskstate"
    working_dir: str | None = None
    timeout_ms: int = 3000

    _legacy_aliases: ClassVar[dict[str, str]] = {
        **AdapterConfigBase._legacy_aliases,
        "cli_path": "command",
    }

    @property
    def cli_path(self) -> str:
        return self.command


class ProtocolsConfig(AdapterConfigBase):
    schemas_path: str | None = None
    failure_policy: FailurePolicyName = FailurePolicyName.NEEDS_APPROVAL

    _legacy_aliases: ClassVar[dict[str, str]] = {
        **AdapterConfigBase._legacy_aliases,
        "schemas_dir": "schemas_path",
        "schema_path": "schemas_path",
    }

    @property
    def schemas_dir(self) -> str | None:
        return self.schemas_path


class WorkflowConfig(AdapterConfigBase):
    cookbook_path: str | None = None
    timeout_ms: int = 2000
    failure_policy: FailurePolicyName = FailurePolicyName.NEEDS_APPROVAL

    _legacy_aliases: ClassVar[dict[str, str]] = {
        **AdapterConfigBase._legacy_aliases,
        "docs_path": "cookbook_path",
    }


class AdaptersConfig(_ConfigModel):
    gatefield: GatefieldConfig = Field(default_factory=GatefieldConfig)
    taskstate: TaskstateConfig = Field(default_factory=TaskstateConfig)
    protocols: ProtocolsConfig = Field(default_factory=ProtocolsConfig)
    memx: MemxConfig = Field(default_factory=MemxConfig)
    shipyard: ShipyardConfig = Field(default_factory=ShipyardConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)


class DatabaseConfig(_ConfigModel):
    url: SecretStr = SecretStr("sqlite:///agent-state-gate.db")
    echo: bool = False

    @property
    def is_postgresql(self) -> bool:
        return self.url.get_secret_value().startswith(("postgresql://", "postgresql+psycopg://"))


class OIDCConfig(_ConfigModel):
    enabled: bool = False
    issuer: str | None = None
    audience: str | None = None
    jwks_url: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    subject_claim: str = "sub"
    tenant_claim: str = "tenant_id"
    roles_claim: str = "roles"
    jwks_cache_seconds: int = Field(default=300, ge=1, le=86_400)


class AppConfig(_ConfigModel):
    version: str = "0.5.0"
    runtime_profile: RuntimeProfile = RuntimeProfile.LOCAL_ADVISORY
    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    oidc: OIDCConfig = Field(default_factory=OIDCConfig)
    verdict: dict[str, Any] = Field(default_factory=dict)
    human_queue: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    mcp: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_environment(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        environment = data.pop("environment", None)
        if environment is not None and "runtime_profile" not in data:
            mapping = {
                "local": RuntimeProfile.LOCAL_ADVISORY.value,
                "ci": RuntimeProfile.CI_CONTRACT.value,
                "staging": RuntimeProfile.STAGING_ENFORCE.value,
                "production": RuntimeProfile.PRODUCTION_ENFORCE.value,
            }
            if environment not in mapping:
                raise ValueError(f"Unsupported legacy environment: {environment}")
            warnings.warn(
                "Configuration key 'environment' is deprecated; use 'runtime_profile'.",
                DeprecationWarning,
                stacklevel=3,
            )
            data["runtime_profile"] = mapping[environment]
        return data

    @model_validator(mode="after")
    def _validate_runtime_requirements(self) -> AppConfig:
        if self.runtime_profile in {
            RuntimeProfile.STAGING_ENFORCE,
            RuntimeProfile.PRODUCTION_SHADOW,
            RuntimeProfile.PRODUCTION_ENFORCE,
        } and not self.database.is_postgresql:
            raise ValueError(f"{self.runtime_profile.value} requires PostgreSQL")
        if self.runtime_profile.is_production:
            if not self.oidc.enabled or not self.oidc.issuer or not self.oidc.audience:
                raise ValueError(f"{self.runtime_profile.value} requires configured OIDC")
            disabled = [
                name
                for name in ("gatefield", "taskstate", "protocols", "memx", "shipyard", "workflow")
                if not getattr(self.adapters, name).enabled
            ]
            if disabled:
                raise ValueError(f"Production profiles require enabled adapters: {', '.join(disabled)}")
        return self


def _expand_environment(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if not isinstance(value, str):
        return value
    match = _ENV_PATTERN.fullmatch(value)
    if not match:
        return value
    name, default = match.groups()
    resolved = os.getenv(name, default)
    if resolved is None:
        raise ValueError(f"Environment variable '{name}' is required")
    return resolved


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    return AppConfig.model_validate(_expand_environment(raw))


__all__ = [
    "AdapterConfigBase",
    "AdaptersConfig",
    "AppConfig",
    "DatabaseConfig",
    "FailurePolicyName",
    "GatefieldConfig",
    "HTTPAdapterConfig",
    "MemxConfig",
    "OIDCConfig",
    "ProtocolsConfig",
    "RuntimeProfile",
    "ShipyardConfig",
    "TaskstateConfig",
    "WorkflowConfig",
    "load_config",
]

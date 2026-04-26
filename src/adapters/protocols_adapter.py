"""
ProtocolsAdapter Module

Adapter for agent-protocols schemas and validation.
Provides risk level derivation and approval rule resolution.

Reference: adapter_contract.md Section 3, 10.3
Reference: agent-protocols schemas/
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .base import (
    AdapterMetadata,
    BaseAdapter,
    FailurePolicy,
    OperationMode,
    SchemaValidationError,
)

# Risk capability mappings (adapter_contract.md:327-343)
CRITICAL_CAPABILITIES: set[str] = {
    "production_data_access",
    "external_secret",
    "rollback_impossible",
}

HIGH_CAPABILITIES: set[str] = {
    "install_deps",
    "network_access",
    "read_secrets",
    "publish_release",
}

MEDIUM_CAPABILITIES: set[str] = {
    "write_repo",
}


# Approval matrix (adapter_contract.md:340-345)
APPROVAL_MATRIX: dict[str, dict[str, Any]] = {
    "low": {"required_approvals": [], "auto_approved": True},
    "medium": {"required_approvals": [], "auto_approved": True},
    "high": {
        "required_approvals": ["project_lead", "security_reviewer"],
        "auto_approved": False,
    },
    "critical": {
        "required_approvals": ["project_lead", "security_reviewer", "release_manager"],
        "auto_approved": False,
    },
}


@dataclass
class ProtocolsConfig:
    """Configuration for ProtocolsAdapter."""
    schemas_dir: str | None = None  # Path to agent-protocols schemas/
    enabled: bool = True


class ProtocolsAdapter(BaseAdapter):
    """
    Adapter for agent-protocols schema definitions.

    Capabilities:
    - Derive risk level from capabilities
    - Derive required approvals from risk level
    - Resolve definition of done for contract type
    - Resolve publish requirements for target
    - Validate contract against schema

    Operation Mode: read-only
    Failure Policy: needs-approval on validation failure
    """

    def __init__(self, config: dict[str, Any] = None):
        self._config = ProtocolsConfig(**(config or {}))
        self._schemas_path = (
            Path(self._config.schemas_dir) if self._config.schemas_dir
            else Path(__file__).parent.parent.parent.parent / "agent-protocols" / "schemas"
        )

    @property
    def name(self) -> str:
        return "protocols"

    @property
    def capability(self) -> str:
        return "contract-risk-approval"

    def health_check(self) -> bool:
        """Check agent-protocols schemas directory exists."""
        try:
            return self._schemas_path.exists() and self._schemas_path.is_dir()
        except Exception:
            return False

    def get_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.name,
            capability=self.capability,
            operation_mode=OperationMode.READ_ONLY,
            timeout_ms=1000,  # Local FS, fast
            failure_policy=FailurePolicy.NEEDS_APPROVAL,
            audit_required=False
        )

    def derive_risk_level(
        self,
        capabilities: list[str],
        context: dict[str, Any] | None = None
    ) -> str:
        """
        Derive risk level from capabilities.

        Args:
            capabilities: List of capability strings.
            context: Optional context dict for additional factors.

        Returns:
            risk_level: "low" | "medium" | "high" | "critical"

        Reference: adapter_contract.md:327-343
        """
        cap_set = set(capabilities)

        # Check critical capabilities
        if cap_set & CRITICAL_CAPABILITIES:
            return "critical"

        # Check high capabilities
        if cap_set & HIGH_CAPABILITIES:
            return "high"

        # Check medium capabilities
        if cap_set & MEDIUM_CAPABILITIES:
            return "medium"

        return "low"

    def derive_required_approvals(
        self,
        risk_level: str,
        capabilities: list[str] | None = None
    ) -> list[str]:
        """
        Derive required approvals from risk level.

        Args:
            risk_level: Risk level string.
            capabilities: Optional capabilities for additional rules.

        Returns:
            List of approver role strings.

        Reference: adapter_contract.md:340-345
        """
        level = risk_level.lower()
        if level not in APPROVAL_MATRIX:
            raise SchemaValidationError(f"Unknown risk level: {risk_level}")

        return APPROVAL_MATRIX[level]["required_approvals"]

    def is_auto_approved(
        self,
        risk_level: str
    ) -> bool:
        """
        Check if risk level allows auto-approval.

        Args:
            risk_level: Risk level string.

        Returns:
            True if auto-approval allowed.
        """
        level = risk_level.lower()
        if level not in APPROVAL_MATRIX:
            return False
        return APPROVAL_MATRIX[level]["auto_approved"]

    def resolve_definition_of_done(
        self,
        contract_type: str
    ) -> dict[str, Any]:
        """
        Resolve definition of done for contract type.

        Args:
            contract_type: Contract type (Intent, Task, Acceptance, Publish, Evidence).

        Returns:
            Definition of done schema dict.

        Raises:
            SchemaValidationError: If schema not found.
        """
        schema_file = self._schemas_path / "contract_types" / f"{contract_type.lower()}.schema.json"

        if not schema_file.exists():
            raise SchemaValidationError(
                f"Contract type schema not found: {contract_type}"
            )

        try:
            with open(schema_file, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Schema JSON decode error: {e}")

    def resolve_publish_requirements(
        self,
        target: str
    ) -> dict[str, Any]:
        """
        Resolve publish requirements for target.

        Args:
            target: Publish target (npm, pypi, docker, etc.).

        Returns:
            Publish gate schema dict.

        Raises:
            SchemaValidationError: If schema not found.
        """
        schema_file = self._schemas_path / "publish_gates" / f"{target.lower()}.schema.json"

        if not schema_file.exists():
            raise SchemaValidationError(
                f"Publish gate schema not found: {target}"
            )

        try:
            with open(schema_file, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(f"Schema JSON decode error: {e}")

    def validate_contract(
        self,
        contract: dict[str, Any],
        contract_type: str
    ) -> bool:
        """
        Validate contract against schema.

        Args:
            contract: Contract dict to validate.
            contract_type: Contract type.

        Returns:
            True if valid.

        Raises:
            SchemaValidationError: If validation fails.
        """
        schema = self.resolve_definition_of_done(contract_type)

        # Basic schema validation (key presence check)
        required_keys = schema.get("required", [])
        for key in required_keys:
            if key not in contract:
                raise SchemaValidationError(
                    f"Missing required field: {key}"
                )

        return True

    def get_risk_levels_schema(self) -> dict[str, Any]:
        """
        Load risk levels schema.

        Returns:
            Risk levels schema dict.
        """
        schema_file = self._schemas_path / "risk_levels.yaml"

        if not schema_file.exists():
            # Return default schema
            return {
                "levels": ["low", "medium", "high", "critical"],
                "critical_capabilities": list(CRITICAL_CAPABILITIES),
                "high_capabilities": list(HIGH_CAPABILITIES),
                "medium_capabilities": list(MEDIUM_CAPABILITIES),
            }

        try:
            with open(schema_file, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError:
            return {}

    def get_approval_matrix_schema(self) -> dict[str, Any]:
        """
        Load approval matrix schema.

        Returns:
            Approval matrix schema dict.
        """
        schema_file = self._schemas_path / "approval_matrix.yaml"

        if not schema_file.exists():
            # Return default matrix
            return APPROVAL_MATRIX

        try:
            with open(schema_file, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except yaml.YAMLError:
            return APPROVAL_MATRIX

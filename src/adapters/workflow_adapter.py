"""
WorkflowAdapter Module

Adapter for workflow-cookbook CLI and file access.
Provides evidence reports, acceptance, and governance policy access.

Reference: adapter_contract.md Section 6, 10.6
Reference: workflow-cookbook tools/ci/generate_evidence_report.py
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .base import (
    AdapterMetadata,
    AdapterUnavailableError,
    BaseAdapter,
    EvidenceNotFoundError,
    FailurePolicy,
    OperationMode,
)


@dataclass
class WorkflowConfig:
    """Configuration for WorkflowAdapter."""
    cookbook_path: str | None = None  # Path to workflow-cookbook repo
    timeout_seconds: int = 2
    enabled: bool = True


class WorkflowAdapter(BaseAdapter):
    """
    Adapter for workflow-cookbook CLI and files.

    Capabilities:
    - Get birdseye capabilities for repo
    - Get acceptance index for task
    - Get governance policy
    - Get evidence report for task/stage
    - Get codemap for scope

    Operation Mode: read-only
    Failure Policy: needs-approval on missing evidence
    """

    def __init__(self, config: dict[str, Any] = None):
        self._config = WorkflowConfig(**(config or {}))
        self._cookbook_path = (
            Path(self._config.cookbook_path) if self._config.cookbook_path
            else Path(__file__).parent.parent.parent.parent / "workflow-cookbook"
        )

    @property
    def name(self) -> str:
        return "workflow"

    @property
    def capability(self) -> str:
        return "evidence-acceptance-governance"

    def health_check(self) -> bool:
        """Check workflow-cookbook availability."""
        try:
            acceptance_dir = self._cookbook_path / "docs" / "acceptance"
            return acceptance_dir.exists() and acceptance_dir.is_dir()
        except Exception:
            return False

    def get_metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.name,
            capability=self.capability,
            operation_mode=OperationMode.READ_ONLY,
            timeout_ms=self._config.timeout_seconds * 1000,
            failure_policy=FailurePolicy.NEEDS_APPROVAL,
            audit_required=False
        )

    def _run_cli(
        self,
        script_path: str,
        args: list[str]
    ) -> dict[str, Any]:
        """Execute workflow-cookbook CLI script."""
        full_path = self._cookbook_path / script_path

        if not full_path.exists():
            raise AdapterUnavailableError(
                self.name,
                f"Script not found: {script_path}"
            )

        try:
            result = subprocess.run(
                ["python", str(full_path)] + args,
                capture_output=True,
                timeout=self._config.timeout_seconds,
                cwd=str(self._cookbook_path)
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                raise AdapterUnavailableError(
                    self.name,
                    f"CLI error: {stderr}"
                )

            return json.loads(result.stdout.decode("utf-8"))

        except subprocess.TimeoutExpired:
            raise AdapterUnavailableError(self.name, "CLI timeout")
        except json.JSONDecodeError as e:
            raise AdapterUnavailableError(self.name, f"JSON decode error: {e}")

    def get_birdseye_caps(
        self,
        repo_path: str
    ) -> dict[str, Any]:
        """
        Get birdseye capabilities for repo.

        Args:
            repo_path: Repository path.

        Returns:
            Dict with capabilities, roles.
        """
        # Run codemap update to get birdseye
        try:
            self._run_cli(
                "tools/codemap/update.py",
                ["--radius", "2", "--repo", repo_path]
            )
        except AdapterUnavailableError:
            # Fallback to reading existing birdseye
            pass

        # Read birdseye index
        birdseye_path = Path(repo_path) / "birdseye" / "index.json"

        if not birdseye_path.exists():
            # Return empty capabilities
            return {"capabilities": [], "roles": []}

        try:
            with open(birdseye_path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"capabilities": [], "roles": []}

    def get_acceptance_index(
        self,
        task_id: str
    ) -> dict[str, Any]:
        """
        Get acceptance index for task.

        Args:
            task_id: Task identifier.

        Returns:
            AcceptanceIndex dict.
        """
        acceptance_dir = self._cookbook_path / "docs" / "acceptance"

        if not acceptance_dir.exists():
            return {"acceptances": [], "task_id": task_id}

        # Scan acceptance files for matching task_id
        acceptances = []
        for f in acceptance_dir.glob("*.md"):
            # Parse acceptance file for task_id
            try:
                content = f.read_text(encoding="utf-8")
                if task_id in content:
                    acceptances.append({
                        "id": f.stem,
                        "task_id": task_id,
                        "file": str(f),
                    })
            except Exception:
                continue

        return {"acceptances": acceptances, "task_id": task_id}

    def get_governance_policy(
        self,
        policy_id: str
    ) -> dict[str, Any]:
        """
        Get governance policy by ID.

        Args:
            policy_id: Policy identifier.

        Returns:
            GovernancePolicy dict.
        """
        policy_file = self._cookbook_path / "governance" / f"{policy_id}.yaml"

        if not policy_file.exists():
            # Check default policy
            policy_file = self._cookbook_path / "governance" / "policy.yaml"

        if not policy_file.exists():
            return {"policy_id": policy_id, "rules": []}

        try:
            with open(policy_file, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {"policy_id": policy_id, "rules": []}

    def get_evidence_report(
        self,
        task_id: str,
        stage: str | None = None
    ) -> dict[str, Any]:
        """
        Get evidence report for task/stage.

        Args:
            task_id: Task identifier.
            stage: Optional stage filter.

        Returns:
            EvidenceReport dict (adapter_contract.md:562-593 format).

        Raises:
            EvidenceNotFoundError: If evidence not found.
        """
        try:
            args = ["--task", task_id]
            if stage:
                args.extend(["--stage", stage])

            result = self._run_cli(
                "tools/ci/generate_evidence_report.py",
                args
            )
            return result

        except AdapterUnavailableError:
            # Fallback to reading evidence file directly
            evidence_path = self._cookbook_path / ".workflow-cache" / "evidence.json"

            if not evidence_path.exists():
                raise EvidenceNotFoundError(task_id)

            try:
                with open(evidence_path, encoding="utf-8") as f:
                    data = json.load(f)

                # Filter by task_id if needed
                evidences = data.get("evidences", [])
                filtered = [e for e in evidences if e.get("task_id") == task_id]

                return {
                    "acceptances": data.get("acceptances", []),
                    "evidences": filtered,
                    "linked": data.get("linked", []),
                    "unlinked_acceptances": data.get("unlinked_acceptances", []),
                    "unlinked_evidences": data.get("unlinked_evidences", []),
                }
            except json.JSONDecodeError:
                raise EvidenceNotFoundError(task_id)

    def get_codemap(
        self,
        scope: str
    ) -> dict[str, Any]:
        """
        Get codemap for scope.

        Args:
            scope: Scope identifier.

        Returns:
            Codemap dict.
        """
        try:
            result = self._run_cli(
                "tools/codemap/update.py",
                ["--scope", scope]
            )
            return result
        except AdapterUnavailableError:
            # Fallback to reading existing codemap
            codemap_path = self._cookbook_path / "codemap" / f"{scope}.json"

            if not codemap_path.exists():
                return {"scope": scope, "modules": []}

            try:
                with open(codemap_path, encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {"scope": scope, "modules": []}

"""
Assessment Store

In-memory assessment store for MVP.
"""

from agent_state_gate.typed_ref import (
    assessment_ref,
    parse_ref,
)

from .types import Assessment


class AssessmentStore:
    """
    In-memory assessment store for MVP.

    Stores Assessment canonical copies in agent-state-gate.
    Future: Replace with persistent DB backend.
    """

    def __init__(self):
        self._assessments: dict[str, Assessment] = {}

    def save(self, assessment: Assessment) -> str:
        """
        Save assessment to store.

        Args:
            assessment: Assessment instance.

        Returns:
            assessment_ref (typed_ref format).
        """
        self._assessments[assessment.assessment_id] = assessment
        return assessment_ref(assessment.assessment_id)

    def get(self, assessment_ref_str: str) -> Assessment | None:
        """
        Get assessment by typed_ref.

        Args:
            assessment_ref_str: Assessment typed_ref string.

        Returns:
            Assessment instance or None if not found.
        """
        try:
            if ":" not in assessment_ref_str:
                return self._assessments.get(assessment_ref_str)
            parsed = parse_ref(assessment_ref_str)
            if parsed.domain != "agent-state-gate" or parsed.entity_type != "assessment":
                return None
            return self._assessments.get(parsed.entity_id)
        except ValueError:
            return None

    def get_by_id(self, assessment_id: str) -> Assessment | None:
        """
        Get assessment by ID.

        Args:
            assessment_id: Assessment ID string.

        Returns:
            Assessment instance or None.
        """
        return self._assessments.get(assessment_id)

    def list_by_task(self, task_id: str) -> list[Assessment]:
        """
        List assessments for a task.

        Args:
            task_id: Task ID.

        Returns:
            List of assessments for task.
        """
        return [
            a for a in self._assessments.values()
            if a.task_id == task_id
        ]

    def list_by_run(self, run_id: str) -> list[Assessment]:
        """
        List assessments for a run.

        Args:
            run_id: Run ID.

        Returns:
            List of assessments for run.
        """
        return [
            a for a in self._assessments.values()
            if a.run_id == run_id
        ]


__all__ = ["AssessmentStore"]

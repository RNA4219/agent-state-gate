"""
Adapter Registry Module

Manages registration and lookup of all agent-state-gate adapters.
Provides health check aggregation and capability-based lookup.
"""


from .base import BaseAdapter


class AdapterRegistry:
    """
    Registry for managing adapter instances.

    Features:
    - Register adapters by name
    - Lookup by name or capability
    - Aggregate health checks
    - Initialize from config
    """

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}

    def register(self, adapter: BaseAdapter) -> None:
        """
        Register an adapter instance.

        Args:
            adapter: BaseAdapter instance to register.

        Raises:
            ValueError: If adapter name already registered.
        """
        name = adapter.name
        if name in self._adapters:
            raise ValueError(f"Adapter '{name}' already registered")
        self._adapters[name] = adapter

    def get(self, name: str) -> BaseAdapter | None:
        """
        Get adapter by name.

        Args:
            name: Adapter name (e.g., 'gatefield', 'taskstate').

        Returns:
            BaseAdapter instance or None if not found.
        """
        return self._adapters.get(name)

    def get_all(self) -> list[BaseAdapter]:
        """
        Get all registered adapters.

        Returns:
            List of all BaseAdapter instances.
        """
        return list(self._adapters.values())

    def get_names(self) -> list[str]:
        """
        Get all registered adapter names.

        Returns:
            List of adapter names.
        """
        return list(self._adapters.keys())

    def health_check_all(self) -> dict[str, bool]:
        """
        Run health check on all adapters.

        Returns:
            Dict mapping adapter name to health status (True/False).
        """
        result: dict[str, bool] = {}
        for name, adapter in self._adapters.items():
            try:
                result[name] = adapter.health_check()
            except Exception:
                result[name] = False
        return result

    def get_by_capability(self, capability: str) -> list[BaseAdapter]:
        """
        Find adapters matching a capability.

        Args:
            capability: Capability string to match.

        Returns:
            List of matching BaseAdapter instances.
        """
        return [
            adapter
            for adapter in self._adapters.values()
            if adapter.capability == capability
        ]

    def unregister(self, name: str) -> bool:
        """
        Remove an adapter from registry.

        Args:
            name: Adapter name to remove.

        Returns:
            True if removed, False if not found.
        """
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False

    def clear(self) -> None:
        """Remove all adapters from registry."""
        self._adapters.clear()

    def __len__(self) -> int:
        """Return number of registered adapters."""
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        """Check if adapter is registered."""
        return name in self._adapters


def initialize_adapters(config: dict) -> AdapterRegistry:
    """
    Initialize adapters from configuration.

    Args:
        config: Configuration dict with adapter settings.

    Returns:
        AdapterRegistry with configured adapters.

    Note:
        This function imports adapter modules dynamically to avoid
        circular imports. Adapters are only loaded if enabled in config.
    """
    registry = AdapterRegistry()
    adapters_config = config.get("adapters", {})

    # Gatefield (required for state-space gate)
    if adapters_config.get("gatefield", {}).get("enabled", False):
        from .gatefield_adapter import GatefieldAdapter
        registry.register(GatefieldAdapter(adapters_config["gatefield"]))

    # Taskstate (required for task/run)
    if adapters_config.get("taskstate", {}).get("enabled", False):
        from .taskstate_adapter import TaskstateAdapter
        registry.register(TaskstateAdapter(adapters_config["taskstate"]))

    # Protocols (required for risk/approval)
    if adapters_config.get("protocols", {}).get("enabled", False):
        from .protocols_adapter import ProtocolsAdapter
        registry.register(ProtocolsAdapter(adapters_config["protocols"]))

    # Memx (required for docs/stale)
    if adapters_config.get("memx", {}).get("enabled", False):
        from .memx_adapter import MemxAdapter
        registry.register(MemxAdapter(adapters_config["memx"]))

    # Shipyard (required for stage/publish)
    if adapters_config.get("shipyard", {}).get("enabled", False):
        from .shipyard_adapter import ShipyardAdapter
        registry.register(ShipyardAdapter(adapters_config["shipyard"]))

    # Workflow (required for evidence/acceptance)
    if adapters_config.get("workflow", {}).get("enabled", False):
        from .workflow_adapter import WorkflowAdapter
        registry.register(WorkflowAdapter(adapters_config["workflow"]))

    return registry

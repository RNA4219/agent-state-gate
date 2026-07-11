"""agent-state-gate 0.4 compatibility shim.

Only the public top-level exports are kept for the 0.5 release. Import from
``agent_state_gate`` instead. This shim is scheduled for removal in 0.6.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "The 'src' package is deprecated; import from 'agent_state_gate'. "
    "Compatibility will be removed in 0.6.",
    DeprecationWarning,
    stacklevel=2,
)

from agent_state_gate import *  # noqa: E402,F403
from agent_state_gate import __all__, __version__  # noqa: E402,F401


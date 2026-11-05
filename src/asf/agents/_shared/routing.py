"""Automatic model-tier routing, shared by the AI agents.

Model choice in ASF is automatic: the service classifies each run's
requirement when the run starts (see ``FactoryService.start_run``) and
records the tier in the run context as ``modelTier``. A run whose
requirement is oversized is ``"complex"``: its documents and code are
long, and the economy per-agent models are exactly the ones that
truncate or lose the format on such work (a real run died that way:
the spec came back with 2 of 7 sections from the cheap model).

Agents copy the tier into their model-request metadata via
:func:`tier_metadata`; the settings routing gateway then upgrades
every call of a complex run to the shared configured model — the
strongest one the user picked — overriding the per-agent economy
assignments. Standard runs carry no tier and route per agent as
configured, so simple work keeps costing the cheap models.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TIER_COMPLEX = "complex"


def model_tier(context: Mapping[str, Any] | None) -> str | None:
    """The run's model tier from its context, or None for standard."""
    if not isinstance(context, Mapping):
        return None
    tier = context.get("modelTier")
    return tier if tier == TIER_COMPLEX else None


def tier_metadata(context: Mapping[str, Any] | None) -> dict[str, str]:
    """Model-request metadata carrying the tier (empty when standard)."""
    tier = model_tier(context)
    return {"modelTier": tier} if tier is not None else {}

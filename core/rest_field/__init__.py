"""Synthetic rest-field substrate.

Biological language around rest, sleep, and entrainment is inspiration only.
The package exposes synthetic relationships, explicit source provenance, and
divertible junctions; it does not assert physiology or prescribe experience.
"""

from .organ import (
    DIMENSIONS,
    JUNCTION_MODES,
    SOURCE_KINDS,
    JunctionRegistry,
    RestField,
    RestObserver,
    RestSourceRegistry,
    canonical_config_hash,
)
from .runtime import RestRuntime
from .resource_ecology import (
    RESOURCE_SPECS,
    project_resource_ecology,
)
from .assimilation import (
    OPERATOR_ID as ASSIMILATION_OPERATOR_ID,
    RESOURCE_ID as ASSIMILATION_RESOURCE_ID,
    project_quiet_assimilation,
)
from .sources import (
    assembly_pressure,
    calibration_source_specs,
    consolidation_backlog,
    continuity_load,
    interaction_forcing,
    rhythm_variation,
    somatic_activity,
)

__all__ = [
    "DIMENSIONS",
    "JUNCTION_MODES",
    "SOURCE_KINDS",
    "JunctionRegistry",
    "RestField",
    "RestObserver",
    "RestSourceRegistry",
    "RestRuntime",
    "RESOURCE_SPECS",
    "ASSIMILATION_OPERATOR_ID",
    "ASSIMILATION_RESOURCE_ID",
    "assembly_pressure",
    "calibration_source_specs",
    "consolidation_backlog",
    "continuity_load",
    "interaction_forcing",
    "rhythm_variation",
    "project_resource_ecology",
    "project_quiet_assimilation",
    "somatic_activity",
    "canonical_config_hash",
]

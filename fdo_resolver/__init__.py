"""fdo_resolver – Resolve RO-Crate FAIR Digital Object inputs for scientific workflows."""

from fdo_resolver.resolver import (
    FDOResolver,
    ResolvedBindings,
    VariableDescription,
)

__all__ = ["FDOResolver", "ResolvedBindings", "VariableDescription"]
__version__ = "0.2.0"

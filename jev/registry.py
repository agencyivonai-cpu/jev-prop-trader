from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType


@dataclass(frozen=True)
class ModelSpec:
    name: str
    risk_usd: Decimal


class Registry:
    def __init__(self, specs):
        models = {}
        for spec in specs:
            if not spec.name or spec.name in models:
                raise ValueError("Model names must be nonempty and unique")
            if not spec.risk_usd.is_finite() or spec.risk_usd <= 0:
                raise ValueError("Explicit positive finite risk required")
            models[spec.name] = spec
        self.models = MappingProxyType(models)

    def get(self, name):
        return self.models.get(name)  # No fallback risk.


def challenger_registry():
    return Registry(ModelSpec(name, Decimal("60")) for name in
                    ("jev_vwap_reclaim", "jev_or_breakout", "jev_level_rejection"))

"""Domain-specific metrics, units and minimum comparison context."""

from dataclasses import dataclass
from enum import StrEnum


class Domain(StrEnum):
    AUTO = "auto"
    CHEMICAL = "chemical_engineering"
    ENERGY = "energy"
    COMPUTING = "computer_science"
    MEDICINE = "medicine"
    PHYSICS = "physics"
    BIOLOGY = "biology"
    ENVIRONMENT = "environmental_science"
    MATERIALS = "materials_science"
    BUSINESS = "business"


@dataclass(frozen=True)
class DomainSchema:
    metrics: dict[str, tuple[str, ...]]
    required_context: tuple[str, ...]


MASS_YIELD = ("mol/kg", "mmol/g", "g/kg", "L/kg", "%")
SCHEMAS = {
    Domain.CHEMICAL: DomainSchema(
        {"hydrogen yield": MASS_YIELD, "carbon conversion efficiency": ("%",), "cold gas efficiency": ("%",),
         "conversion": ("%",), "higher heating value": ("MJ/kg",), "tar concentration": ("mg/m³",),
         "syngas yield": MASS_YIELD},
        ("feedstock", "reactor", "temperature", "pressure", "basis", "method"),
    ),
    Domain.ENERGY: DomainSchema(
        {"energy density": ("Wh/kg", "Wh/L", "MJ/kg"), "capacity retention": ("%",)},
        ("material", "cycle count", "method"),
    ),
    Domain.COMPUTING: DomainSchema(
        {"classification accuracy": ("%",), "inference latency": ("ms", "s"),
         "f1 score": ("%", "unitless")},
        ("dataset", "split", "method", "hardware"),
    ),
    Domain.MEDICINE: DomainSchema(
        {"absolute risk reduction": ("%", "percentage points"), "diagnostic sensitivity": ("%",),
         "odds ratio": ("unitless",)},
        ("population", "endpoint", "follow-up", "comparator", "method"),
    ),
    Domain.PHYSICS: DomainSchema(
        {"electrical resistivity": ("Ω·m", "Ω·cm"), "thermal conductivity": ("W/m·K", "W/(m·K)")},
        ("material", "temperature", "method"),
    ),
    Domain.BIOLOGY: DomainSchema(
        {"species richness": ("species",), "relative abundance": ("%",)},
        ("species", "sample type", "method"),
    ),
    Domain.ENVIRONMENT: DomainSchema(
        {"particulate concentration": ("µg/m³", "mg/m³"), "nitrate concentration": ("mg/L", "µg/L")},
        ("location", "sample type", "method"),
    ),
    Domain.MATERIALS: DomainSchema(
        {"tensile strength": ("MPa", "GPa"), "young's modulus": ("MPa", "GPa")},
        ("material", "temperature", "method", "specimen"),
    ),
    Domain.BUSINESS: DomainSchema(
        {"gross margin": ("%",), "return on investment": ("%",)},
        ("population", "period", "basis", "method"),
    ),
}
METRIC_DOMAINS = {name: domain for domain, schema in SCHEMAS.items() for name in schema.metrics}

"""
models.py
Input and output schemas for the Should-Cost engine.
Implemented with stdlib dataclasses + manual validation (no external deps).
AI (explain.py) reads CostEstimate outputs but never modifies them.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ─── ENUMS ────────────────────────────────────────────────────────────────────

class Material(str, Enum):
    AL_6061     = "AL-6061"
    AL_7075     = "AL-7075"
    SS_304      = "SS-304"
    SS_17_4     = "SS-17-4"
    TI_6AL4V    = "Ti-6Al-4V"
    INCONEL_718 = "Inconel-718"
    STEEL_4130  = "Steel-4130"
    STEEL_4340  = "Steel-4340"


class ComplexityTier(int, Enum):
    SIMPLE    = 1
    LOW       = 2
    MEDIUM    = 3
    HIGH      = 4
    VERY_HIGH = 5


class ToleranceTier(str, Enum):
    STANDARD = "standard"
    TIGHT    = "tight"


class Region(str, Enum):
    US   = "US"
    EU   = "EU"
    ASIA = "Asia"


class OutsideProcess(str, Enum):
    HEAT_TREAT      = "heat_treat"
    ANODIZE         = "anodize"
    HARD_ANODIZE    = "hard_anodize"
    CHROMATE        = "chromate"
    NICKEL_PLATE    = "nickel_plate"
    PASSIVATION     = "passivation"
    SHOT_PEEN       = "shot_peen"
    INSPECTION_CMM  = "inspection_cmm"
    PAINT           = "paint"


class ConfidenceLevel(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"


class OverrideSource(str, Enum):
    VERIFIED   = "verified"    # from routing, CAM output, or supplier process sheet — no demerit
    UNVERIFIED = "unverified"  # user estimate — demerit applied


# ─── GEOMETRY INPUTS ──────────────────────────────────────────────────────────

@dataclass
class GeometryInputs:
    """
    Raw STEP metrics + derived fields from geometry/step_reader.py.
    All fields are Optional — parse_success=False means all are None.
    """
    parse_success:              bool
    volume_in3:                 Optional[float] = None
    bbox_x:                     Optional[float] = None   # longest dimension
    bbox_y:                     Optional[float] = None
    bbox_z:                     Optional[float] = None   # shortest dimension
    bbox_volume_in3:            Optional[float] = None
    surface_area_in2:           Optional[float] = None
    envelope_to_volume_ratio:   Optional[float] = None   # bbox_volume / volume
    slenderness_ratio:          Optional[float] = None   # bbox_x / bbox_z
    material_hint:              Optional[str]   = None   # from STEP metadata if present
    finished_weight_lb_derived: Optional[float] = None   # volume_in3 x material density
    btf_suggested:              Optional[float] = None   # output of piecewise mapping
    btf_source:                 Optional[str]   = None   # step_derived | tier_default | manual


# ─── INPUT SCHEMA ─────────────────────────────────────────────────────────────

class PartInputs:
    """
    Input schema for a single part estimate.
    Manual __init__ with validation — no external deps required.
    """

    def __init__(
        self,
        part_id: str,
        part_description: str,
        material: Material,
        finished_weight_lb: float,
        complexity_tier: ComplexityTier,
        tolerance_tier: ToleranceTier,
        annual_volume: int,
        batch_size: int,
        region: Region,
        machining_hours_override: Optional[float] = None,
        setup_hours_override: Optional[float] = None,
        override_source: "OverrideSource" = None,
        outside_processes: Optional[list] = None,
        program: Optional[str] = None,
        notes: Optional[str] = None,
        geometry: "Optional[GeometryInputs]" = None,
        geometry_source: Optional[str] = None,  # "step" | "manual"
    ):
        if not part_id:
            raise ValueError("part_id is required")
        if finished_weight_lb <= 0:
            raise ValueError("finished_weight_lb must be > 0")
        if finished_weight_lb > 500:
            raise ValueError("finished_weight_lb exceeds 500 lb — verify input")
        if annual_volume < 1:
            raise ValueError("annual_volume must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if batch_size > annual_volume:
            raise ValueError(
                f"batch_size ({batch_size}) cannot exceed annual_volume ({annual_volume})"
            )
        if machining_hours_override is not None and machining_hours_override <= 0:
            raise ValueError("machining_hours_override must be > 0")
        if setup_hours_override is not None and setup_hours_override <= 0:
            raise ValueError("setup_hours_override must be > 0")

        self.part_id = part_id
        self.part_description = part_description
        self.material = material
        self.finished_weight_lb = finished_weight_lb
        self.complexity_tier = complexity_tier
        self.tolerance_tier = tolerance_tier
        self.annual_volume = annual_volume
        self.batch_size = batch_size
        self.region = region
        self.machining_hours_override = machining_hours_override
        self.setup_hours_override = setup_hours_override
        # Default: if overrides supplied without explicit source, treat as unverified
        if override_source is None and (machining_hours_override is not None or setup_hours_override is not None):
            self.override_source = OverrideSource.UNVERIFIED
        else:
            self.override_source = override_source
        self.outside_processes = outside_processes or []
        self.program = program
        self.notes = notes
        self.geometry = geometry
        self.geometry_source = geometry_source or ("step" if geometry and geometry.parse_success else "manual")

    def model_dump(self) -> dict:
        return {
            "part_id":                  self.part_id,
            "part_description":         self.part_description,
            "material":                 self.material,
            "finished_weight_lb":       self.finished_weight_lb,
            "complexity_tier":          self.complexity_tier,
            "tolerance_tier":           self.tolerance_tier,
            "annual_volume":            self.annual_volume,
            "batch_size":               self.batch_size,
            "region":                   self.region,
            "machining_hours_override": self.machining_hours_override,
            "setup_hours_override":     self.setup_hours_override,
            "outside_processes":        self.outside_processes,
            "program":                  self.program,
            "notes":                    self.notes,
        }


# ─── OUTPUT SCHEMA ────────────────────────────────────────────────────────────

@dataclass
class CostBreakdown:
    material_cost:          float
    machining_cost:         float
    setup_cost_per_piece:   float
    outside_process_cost:   float
    scrap_cost:             float
    overhead_cost:          float
    total_cost:             float
    supplier_margin:        float
    unit_price_mid:         float


@dataclass
class PriceBand:
    low:  float
    mid:  float
    high: float


@dataclass
class SensitivityDriver:
    variable:     str
    delta_pct:    float
    delta_dollar: float


@dataclass
class AssumptionsUsed:
    material_price_per_lb:  float
    buy_to_fly_ratio:       float
    machining_hours:        float
    setup_hours:            float
    machine_rate_per_hr:    float
    overhead_rate:          float
    margin_rate:            float
    scrap_factor:           float
    outside_process_costs:  dict


@dataclass
class CostEstimate:
    """
    Full output of estimate_cost(). Single source of truth.
    ai_narrative is populated by explain.py only — never by the engine.
    """
    part_id:            str
    part_description:   str
    material:           str
    region:             str
    annual_volume:      int
    batch_size:         int
    price_band:         PriceBand
    breakdown:          CostBreakdown
    sensitivity:        list
    assumptions_used:   AssumptionsUsed
    confidence:         ConfidenceLevel
    confidence_notes:   list
    notes:              Optional[str] = None
    ai_narrative:       Optional[str] = None
    geometry:           Optional["GeometryInputs"] = None

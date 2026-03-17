"""
geometry/step_reader.py
STEP file parser + buy-to-fly derivation for the Should-Cost engine.

cadquery is an optional dependency. If not installed, parse_step() returns
a GeometryResult with parse_success=False and all fields None. The app
degrades gracefully to manual input — no exception is raised to the user.

BTF derivation (compute_btf_suggested, _btf_from_ratio, _material_modifier)
is pure Python and works regardless of cadquery availability.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

# ─── CADQUERY — OPTIONAL ──────────────────────────────────────────────────────
try:
    import cadquery as cq
    HAS_CADQUERY = True
except ImportError:
    HAS_CADQUERY = False


# ─── CONSTANTS ────────────────────────────────────────────────────────────────

BTF_MIN = 1.2
BTF_MAX = 6.0

# Material density (lb/in3) — keyed to Material enum values
MATERIAL_DENSITY: dict[str, float] = {
    "AL-6061":     0.0975,
    "AL-7075":     0.1010,
    "SS-304":      0.2900,
    "SS-17-4":     0.2820,
    "Ti-6Al-4V":   0.1600,
    "Inconel-718": 0.2970,
    "Steel-4130":  0.2840,
    "Steel-4340":  0.2840,
}

# Material modifier for BTF derivation
_MATERIAL_MODIFIER_MAP: dict[str, float] = {
    "AL-6061":     0.95,
    "AL-7075":     0.95,
    "SS-304":      1.00,
    "SS-17-4":     1.00,
    "Steel-4130":  1.00,
    "Steel-4340":  1.00,
    "Ti-6Al-4V":   1.10,
    "Inconel-718": 1.15,
}

# Piecewise BTF breakpoints: (upper_bound_exclusive, base_btf)
# Last entry upper bound is float('inf')
_BTF_BREAKPOINTS = [
    (1.4, 1.3),
    (1.8, 1.6),
    (2.4, 2.1),
    (3.2, 2.8),
    (4.2, 3.6),
    (float("inf"), 4.5),
]


# ─── RESULT DATACLASS ─────────────────────────────────────────────────────────

@dataclass
class GeometryResult:
    """
    Output of parse_step(). All metric fields are None if parse_success=False.
    """
    parse_success:          bool            = False
    volume_in3:             Optional[float] = None
    bbox_x:                 Optional[float] = None   # longest dim, inches
    bbox_y:                 Optional[float] = None
    bbox_z:                 Optional[float] = None   # shortest dim, inches
    bbox_volume_in3:        Optional[float] = None
    surface_area_in2:       Optional[float] = None
    envelope_to_volume_ratio: Optional[float] = None
    slenderness_ratio:      Optional[float] = None   # bbox_x / bbox_z
    material_hint:          Optional[str]   = None   # from STEP metadata
    # Derived after material selection
    finished_weight_lb:     Optional[float] = None
    btf_suggested:          Optional[float] = None
    btf_source:             Optional[str]   = None   # step_derived | manual | tier_default


# ─── BTF PURE-PYTHON LOGIC ────────────────────────────────────────────────────

def _btf_from_ratio(ratio: float) -> float:
    """Piecewise lookup: envelope-to-volume ratio → base BTF."""
    for upper, base_btf in _BTF_BREAKPOINTS:
        if ratio < upper:
            return base_btf
    return 4.5  # fallback (should never reach here)


def _material_modifier(material: str) -> float:
    """Return the BTF material modifier for a given material string."""
    return _MATERIAL_MODIFIER_MAP.get(material, 1.00)


def compute_btf_suggested(ratio: float, material: str) -> float:
    """
    Full three-step BTF derivation:
      1. Piecewise ratio lookup
      2. Material modifier
      3. Clamp to [BTF_MIN, BTF_MAX]
    """
    base = _btf_from_ratio(ratio)
    modified = base * _material_modifier(material)
    return round(max(BTF_MIN, min(BTF_MAX, modified)), 2)


# ─── STEP PARSER ──────────────────────────────────────────────────────────────

def parse_step(file_path: str, material: Optional[str] = None) -> GeometryResult:
    """
    Parse a STEP file and return a GeometryResult.

    If cadquery is not installed or the file cannot be parsed, returns
    GeometryResult(parse_success=False) — no exception raised.

    material: optional Material enum value string (e.g. "Ti-6Al-4V").
    If provided, finished_weight_lb and btf_suggested are populated.
    """
    if not HAS_CADQUERY:
        return GeometryResult(parse_success=False)

    try:
        import cadquery as cq

        result = cq.importers.importStep(file_path)
        solid = result.val()

        # Volume and bounding box
        volume_mm3 = solid.Volume()
        bb = solid.BoundingBox()

        # Convert mm to inches (cadquery works in mm by default for STEP)
        MM3_TO_IN3 = 0.0000610237
        MM2_TO_IN2 = 0.00155000
        MM_TO_IN   = 0.0393701

        volume_in3 = volume_mm3 * MM3_TO_IN3

        dims_in = sorted([
            bb.xlen * MM_TO_IN,
            bb.ylen * MM_TO_IN,
            bb.zlen * MM_TO_IN,
        ], reverse=True)

        bbox_x, bbox_y, bbox_z = dims_in
        bbox_volume_in3 = bbox_x * bbox_y * bbox_z

        surface_area_in2 = solid.Area() * MM2_TO_IN2

        envelope_to_volume_ratio = bbox_volume_in3 / volume_in3 if volume_in3 > 0 else None
        slenderness_ratio = bbox_x / bbox_z if bbox_z > 0 else None

        # Material hint from STEP metadata (best-effort)
        material_hint = None
        try:
            shapes = result.all()
            if shapes:
                label = shapes[0].label if hasattr(shapes[0], "label") else None
                if label:
                    material_hint = str(label)
        except Exception:
            pass

        # Derived fields if material provided
        finished_weight_lb = None
        btf_suggested = None
        btf_source = None

        if material and material in MATERIAL_DENSITY and volume_in3:
            density = MATERIAL_DENSITY[material]
            finished_weight_lb = round(volume_in3 * density, 3)

        if envelope_to_volume_ratio and material:
            btf_suggested = compute_btf_suggested(envelope_to_volume_ratio, material)
            btf_source = "step_derived"

        return GeometryResult(
            parse_success=True,
            volume_in3=round(volume_in3, 4),
            bbox_x=round(bbox_x, 4),
            bbox_y=round(bbox_y, 4),
            bbox_z=round(bbox_z, 4),
            bbox_volume_in3=round(bbox_volume_in3, 4),
            surface_area_in2=round(surface_area_in2, 3),
            envelope_to_volume_ratio=round(envelope_to_volume_ratio, 4) if envelope_to_volume_ratio else None,
            slenderness_ratio=round(slenderness_ratio, 3) if slenderness_ratio else None,
            material_hint=material_hint,
            finished_weight_lb=finished_weight_lb,
            btf_suggested=btf_suggested,
            btf_source=btf_source,
        )

    except Exception:
        return GeometryResult(parse_success=False)

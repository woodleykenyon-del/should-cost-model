"""
estimator.py
Core should-cost engine. Deterministic. No AI calls.
All cost numbers originate here and only here.

Build order:
  1. Material cost
  2. Machining cost
  3. Setup cost
  4. Outside process cost
  5. Overhead
  6. Supplier margin
  7. Price band (low / mid / high)
  8. Confidence score
"""

from __future__ import annotations
from dataclasses import dataclass

from engine.models import (
    PartInputs,
    CostEstimate,
    CostBreakdown,
    PriceBand,
    SensitivityDriver,
    AssumptionsUsed,
    ConfidenceLevel,
)
from engine import assumptions as A


# ─── INTERNAL HELPERS ─────────────────────────────────────────────────────────

@dataclass
class _CostComponents:
    """Intermediate cost values for a single scenario (low/mid/high)."""
    material_cost:          float
    machining_cost:         float
    setup_cost_per_piece:   float
    outside_process_cost:   float
    scrap_cost:             float
    direct_cost:            float
    overhead_cost:          float
    total_cost:             float
    supplier_margin_dollar: float
    unit_price:             float


def _compute_scenario(
    inputs: PartInputs,
    material_price: float,
    machine_rate: float,
    machining_hours: float,
    setup_hours: float,
    overhead_rate: float,
    margin_rate: float,
    scrap_factor: float,
    outside_costs: dict[str, float],   # process → per-piece cost
    complexity_tier: int,
) -> _CostComponents:
    """Compute all cost components for one price scenario."""

    # 1. Material
    buy_to_fly = A.get_buy_to_fly(inputs.material.value, complexity_tier)
    blank_weight = inputs.finished_weight_lb * buy_to_fly
    material_cost = blank_weight * material_price

    # 2. Machining
    machining_cost = machine_rate * machining_hours

    # 3. Setup (amortized over batch)
    setup_cost_total = setup_hours * machine_rate
    setup_cost_per_piece = setup_cost_total / inputs.batch_size

    # 4. Outside processes
    outside_process_cost = sum(outside_costs.values())

    # 5. Direct cost (pre-overhead)
    direct_cost = (
        material_cost
        + machining_cost
        + setup_cost_per_piece
        + outside_process_cost
    )

    # 6. Scrap
    scrap_cost = direct_cost * scrap_factor
    direct_cost_with_scrap = direct_cost + scrap_cost

    # 7. Overhead — basis determined by overhead_basis setting in assumptions
    overhead_basis = A.get_overhead_basis()
    if overhead_basis == 'labor_machine_only':
        overhead_base = machining_cost + setup_cost_per_piece
    else:  # all_direct (default)
        overhead_base = direct_cost_with_scrap
    overhead_cost = overhead_base * overhead_rate

    # 8. Total cost
    total_cost = direct_cost_with_scrap + overhead_cost

    # 9. Margin
    supplier_margin_dollar = total_cost * margin_rate
    unit_price = total_cost + supplier_margin_dollar

    # 10. Floor check
    floor = A.get_price_floor(complexity_tier)
    unit_price = max(unit_price, floor)

    return _CostComponents(
        material_cost=round(material_cost, 4),
        machining_cost=round(machining_cost, 4),
        setup_cost_per_piece=round(setup_cost_per_piece, 4),
        outside_process_cost=round(outside_process_cost, 4),
        scrap_cost=round(scrap_cost, 4),
        direct_cost=round(direct_cost, 4),
        overhead_cost=round(overhead_cost, 4),
        total_cost=round(total_cost, 4),
        supplier_margin_dollar=round(supplier_margin_dollar, 4),
        unit_price=round(unit_price, 2),
    )


# ─── CONFIDENCE SCORING ───────────────────────────────────────────────────────

def _score_confidence(
    inputs: PartInputs,
) -> tuple[ConfidenceLevel, list[str]]:
    """
    Assign confidence level based on input quality and volatility factors.
    Thresholds and demerit weights are read from assumptions_default.json.

    0 demerits       → High
    1-2 demerits     → Medium
    3+               → Low

    Override logic: verified overrides (from routing/CAM/supplier sheet) do NOT
    trigger a demerit — they improve specificity. Unverified overrides (user
    estimates) DO trigger a demerit.
    """
    from engine.models import OverrideSource
    thresholds = A.get_confidence_thresholds()
    weights = thresholds["demerit_weights"]
    medium_max = thresholds["demerit_medium_max"]
    volatile_materials = A.get_high_volatility_materials()

    demerits = 0
    notes = []

    # Overrides: only demerit if source is unverified (or defaulted to unverified)
    has_override = (
        inputs.machining_hours_override is not None
        or inputs.setup_hours_override is not None
    )
    if has_override:
        if inputs.override_source == OverrideSource.VERIFIED:
            notes.append(
                "Verified override supplied (routing/CAM/supplier sheet) — "
                "specificity improved, no confidence penalty."
            )
        else:
            if inputs.machining_hours_override is not None:
                demerits += weights["unverified_machining_override"]
                notes.append(
                    "Unverified machining hours override — treat as estimate until "
                    "confirmed against routing or CAM output."
                )
            if inputs.setup_hours_override is not None:
                demerits += weights["unverified_setup_override"]
                notes.append(
                    "Unverified setup hours override — treat as estimate until confirmed."
                )

    if len(inputs.outside_processes) > 3:
        demerits += weights["outside_processes_gt_3"]
        notes.append(
            f"{len(inputs.outside_processes)} outside processes — "
            "stacked process cost assumptions increase uncertainty."
        )

    if inputs.material.value in volatile_materials:
        demerits += weights["high_volatility_material"]
        notes.append(
            f"{inputs.material.value} is a high-volatility material — "
            "material price range is wide."
        )

    if inputs.complexity_tier.value == 5:
        demerits += weights["complexity_tier_5"]
        notes.append(
            "Complexity tier 5 — machining hour estimates carry highest uncertainty."
        )

    if demerits == 0:
        level = ConfidenceLevel.HIGH
        notes.append("All inputs present. Standard assumptions applied. No overrides.")
    elif demerits <= medium_max:
        level = ConfidenceLevel.MEDIUM
    else:
        level = ConfidenceLevel.LOW

    return level, notes


# ─── SENSITIVITY ANALYSIS ─────────────────────────────────────────────────────

def _run_sensitivity(
    inputs: PartInputs,
    mid_price: float,
    mid_machining_hours: float,
    mid_setup_hours: float,
    mat: dict,
    rates: dict,
    overhead_rate: float,
    margin_rates: dict,
    scrap_factors: dict,
    outside_costs_mid: dict[str, float],
) -> list[SensitivityDriver]:
    """
    Perturb each key variable by +10% and measure impact on mid unit price.
    Returns top 3 drivers sorted by absolute dollar impact.
    """
    PERTURBATION = 0.10
    drivers = []

    variables = {
        "material_price":   ("material_price",   mat["price_mid"] * (1 + PERTURBATION)),
        "machining_hours":  ("machining_hours",  mid_machining_hours * (1 + PERTURBATION)),
        "machine_rate":     ("machine_rate",     rates["rate_mid"] * (1 + PERTURBATION)),
        "scrap_factor":     ("scrap_factor",     scrap_factors["mid"] * (1 + PERTURBATION)),
    }

    for label, (var_name, perturbed_val) in variables.items():
        kwargs = dict(
            inputs=inputs,
            material_price=mat["price_mid"],
            machine_rate=rates["rate_mid"],
            machining_hours=mid_machining_hours,
            setup_hours=mid_setup_hours,
            overhead_rate=overhead_rate,
            margin_rate=margin_rates["mid"],
            scrap_factor=scrap_factors["mid"],
            outside_costs=outside_costs_mid,
            complexity_tier=inputs.complexity_tier.value,
        )

        if var_name == "material_price":
            kwargs["material_price"] = perturbed_val
        elif var_name == "machining_hours":
            kwargs["machining_hours"] = perturbed_val
        elif var_name == "machine_rate":
            kwargs["machine_rate"] = perturbed_val
        elif var_name == "scrap_factor":
            kwargs["scrap_factor"] = perturbed_val

        perturbed = _compute_scenario(**kwargs)
        delta_dollar = round(perturbed.unit_price - mid_price, 2)
        delta_pct = round((delta_dollar / mid_price) * 100, 2) if mid_price > 0 else 0.0

        drivers.append(SensitivityDriver(
            variable=label,
            delta_pct=delta_pct,
            delta_dollar=delta_dollar,
        ))

    # Return top 3 by absolute dollar impact
    return sorted(drivers, key=lambda d: abs(d.delta_dollar), reverse=True)[:3]


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def estimate_cost(inputs: PartInputs) -> CostEstimate:
    """
    Produce a full should-cost estimate for the given part inputs.
    Returns a CostEstimate object. ai_narrative field is None until
    explain.py is called separately.
    """

    # --- Load assumptions ---
    mat        = A.get_material(inputs.material.value)
    rates      = A.get_machine_rate(inputs.region.value, inputs.complexity_tier.value)
    overhead_r = A.get_overhead_rate(inputs.region.value)
    margin_rs  = A.get_margin_rates(inputs.region.value)
    scrap_fs   = A.get_scrap_factors()

    # --- Resolve machining / setup hours (override or table) ---
    machining_hrs = (
        inputs.machining_hours_override
        if inputs.machining_hours_override is not None
        else A.get_machining_hours(inputs.complexity_tier.value, inputs.tolerance_tier.value)
    )
    setup_hrs = (
        inputs.setup_hours_override
        if inputs.setup_hours_override is not None
        else A.get_setup_hours(inputs.complexity_tier.value)
    )

    # --- Outside process costs (mid) ---
    outside_costs_mid = {}
    outside_costs_low = {}
    outside_costs_high = {}
    for proc in inputs.outside_processes:
        pc = A.get_outside_process_cost(proc.value)
        outside_costs_mid[proc.value]  = pc["mid"]
        outside_costs_low[proc.value]  = pc["low"]
        outside_costs_high[proc.value] = pc["high"]

    # --- Compute three scenarios ---
    mid = _compute_scenario(
        inputs=inputs,
        material_price=mat["price_mid"],
        machine_rate=rates["rate_mid"],
        machining_hours=machining_hrs,
        setup_hours=setup_hrs,
        overhead_rate=overhead_r,
        margin_rate=margin_rs["mid"],
        scrap_factor=scrap_fs["mid"],
        outside_costs=outside_costs_mid,
        complexity_tier=inputs.complexity_tier.value,
    )

    low = _compute_scenario(
        inputs=inputs,
        material_price=mat["price_low"],
        machine_rate=rates["rate_low"],
        machining_hours=machining_hrs,
        setup_hours=setup_hrs,
        overhead_rate=overhead_r,
        margin_rate=margin_rs["low"],
        scrap_factor=scrap_fs["low"],
        outside_costs=outside_costs_low,
        complexity_tier=inputs.complexity_tier.value,
    )

    high = _compute_scenario(
        inputs=inputs,
        material_price=mat["price_high"],
        machine_rate=rates["rate_high"],
        machining_hours=machining_hrs,
        setup_hours=setup_hrs,
        overhead_rate=overhead_r,
        margin_rate=margin_rs["high"],
        scrap_factor=scrap_fs["high"],
        outside_costs=outside_costs_high,
        complexity_tier=inputs.complexity_tier.value,
    )

    # --- Price band ---
    price_band = PriceBand(
        low=low.unit_price,
        mid=mid.unit_price,
        high=high.unit_price,
    )

    # --- CostBreakdown (mid scenario) ---
    breakdown = CostBreakdown(
        material_cost=mid.material_cost,
        machining_cost=mid.machining_cost,
        setup_cost_per_piece=mid.setup_cost_per_piece,
        outside_process_cost=mid.outside_process_cost,
        scrap_cost=mid.scrap_cost,
        overhead_cost=mid.overhead_cost,
        total_cost=mid.total_cost,
        supplier_margin=mid.supplier_margin_dollar,
        unit_price_mid=mid.unit_price,
    )

    # --- Assumptions snapshot ---
    btf = A.get_buy_to_fly(inputs.material.value, inputs.complexity_tier.value)
    assumptions_used = AssumptionsUsed(
        material_price_per_lb=mat["price_mid"],
        buy_to_fly_ratio=btf,
        machining_hours=machining_hrs,
        setup_hours=setup_hrs,
        machine_rate_per_hr=rates["rate_mid"],
        overhead_rate=overhead_r,
        margin_rate=margin_rs["mid"],
        scrap_factor=scrap_fs["mid"],
        outside_process_costs=outside_costs_mid,
    )

    # --- Sensitivity ---
    sensitivity = _run_sensitivity(
        inputs=inputs,
        mid_price=mid.unit_price,
        mid_machining_hours=machining_hrs,
        mid_setup_hours=setup_hrs,
        mat=mat,
        rates=rates,
        overhead_rate=overhead_r,
        margin_rates=margin_rs,
        scrap_factors=scrap_fs,
        outside_costs_mid=outside_costs_mid,
    )

    # --- Confidence ---
    confidence, confidence_notes = _score_confidence(inputs)

    return CostEstimate(
        part_id=inputs.part_id,
        part_description=inputs.part_description,
        material=inputs.material.value,
        region=inputs.region.value,
        annual_volume=inputs.annual_volume,
        batch_size=inputs.batch_size,
        price_band=price_band,
        breakdown=breakdown,
        sensitivity=sensitivity,
        assumptions_used=assumptions_used,
        confidence=confidence,
        confidence_notes=confidence_notes,
    )

"""
assumptions.py
Loads and exposes all cost assumptions to the engine.
Single source of truth for every lookup the estimator needs.
"""

from __future__ import annotations
import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"


# ─── LOADERS ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_json() -> dict:
    path = DATA_DIR / "assumptions_default.json"
    with open(path) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_materials() -> dict[str, dict]:
    """Returns dict keyed by material name."""
    path = DATA_DIR / "materials.csv"
    result = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            result[row["material"]] = {
                "price_low":    float(row["price_low_per_lb"]),
                "price_mid":    float(row["price_mid_per_lb"]),
                "price_high":   float(row["price_high_per_lb"]),
                "density":      float(row["density_lb_per_in3"]),
                "notes":        row["notes"],
            }
    return result


@lru_cache(maxsize=1)
def _load_machine_rates() -> dict[tuple, dict]:
    """Returns dict keyed by (region, machine_type)."""
    path = DATA_DIR / "machine_rates.csv"
    result = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            key = (row["region"], row["machine_type"])
            result[key] = {
                "rate_low":  float(row["rate_low_per_hr"]),
                "rate_mid":  float(row["rate_mid_per_hr"]),
                "rate_high": float(row["rate_high_per_hr"]),
            }
    return result


# ─── PUBLIC ACCESSORS ─────────────────────────────────────────────────────────

def get_material(material: str) -> dict:
    data = _load_materials()
    if material not in data:
        raise KeyError(f"Material '{material}' not found in materials.csv")
    return data[material]


def get_machine_rate(region: str, complexity_tier: int) -> dict:
    assumptions = _load_json()
    machine_type = assumptions["machine_type_by_complexity"][str(complexity_tier)]
    rates = _load_machine_rates()
    key = (region, machine_type)
    if key not in rates:
        raise KeyError(f"No machine rate for region='{region}', machine_type='{machine_type}'")
    return rates[key]


def get_buy_to_fly(material: str, complexity_tier: int) -> float:
    assumptions = _load_json()
    key = f"{material}__{complexity_tier}"
    btf = assumptions["buy_to_fly_ratios"]
    if key not in btf:
        raise KeyError(
            f"No buy-to-fly ratio for material='{material}', complexity={complexity_tier}. "
            f"Add '{key}' to assumptions_default.json."
        )
    return float(btf[key])


def get_machining_hours(complexity_tier: int, tolerance_tier: str) -> float:
    assumptions = _load_json()
    key = f"{complexity_tier}__{tolerance_tier}"
    hours = assumptions["machining_hours"]
    if key not in hours:
        raise KeyError(f"No machining hours entry for key '{key}'")
    return float(hours[key])


def get_setup_hours(complexity_tier: int) -> float:
    assumptions = _load_json()
    return float(assumptions["setup_hours"][str(complexity_tier)])


def get_overhead_rate(region: str) -> float:
    assumptions = _load_json()
    return float(assumptions["overhead_rates"][region])


def get_margin_rates(region: str) -> dict[str, float]:
    assumptions = _load_json()
    return assumptions["margin_rates"][region]


def get_scrap_factors() -> dict[str, float]:
    assumptions = _load_json()
    return assumptions["scrap_factors"]


def get_outside_process_cost(process: str) -> dict[str, float]:
    assumptions = _load_json()
    costs = assumptions["outside_process_costs"]
    if process not in costs:
        raise KeyError(f"Outside process '{process}' not found in assumptions.")
    return costs[process]


def get_price_floor(complexity_tier: int) -> float:
    assumptions = _load_json()
    return float(assumptions["minimum_unit_price_floor"][str(complexity_tier)])


def get_confidence_thresholds() -> dict:
    return _load_json()["confidence_thresholds"]


def get_high_volatility_materials() -> list[str]:
    return _load_json()["high_volatility_materials"]


def get_full_assumptions() -> dict:
    """Return the full assumptions dict — used by Excel exporter."""
    return _load_json()


def get_overhead_basis() -> str:
    """
    Return the overhead basis setting.
    Options: 'all_direct_cost' (default) | 'labor_machine_only'
    Configurable via assumptions_default.json key 'overhead_basis'.
    """
    assumptions = _load_json()
    return assumptions.get("overhead_basis", "all_direct_cost")

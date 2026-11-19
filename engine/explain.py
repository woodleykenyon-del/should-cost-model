"""Plain-language explanations of completed should-cost estimates."""

from engine.models import CostEstimate


_DRIVER_LABELS = {
    "material_price": "material price",
    "machining_hours": "machining time",
    "machine_rate": "machine rate",
    "scrap_factor": "scrap factor",
}


def summarize_estimate(estimate: CostEstimate) -> str:
    """Describe the computed price band, leading sensitivity, and confidence."""
    band = estimate.price_band
    paragraphs = [
        f"The mid estimate is ${band.mid:,.2f} per unit, with modeled scenarios "
        f"ranging from ${band.low:,.2f} to ${band.high:,.2f} per unit. "
        "Use this range as a benchmark when reviewing a supplier quote."
    ]

    if estimate.sensitivity:
        driver = max(estimate.sensitivity, key=lambda item: abs(item.delta_dollar))
        label = _DRIVER_LABELS.get(driver.variable, driver.variable.replace("_", " "))
        if driver.delta_dollar:
            direction = "raises" if driver.delta_dollar > 0 else "lowers"
            paragraphs.append(
                f"Of the inputs tested, {label} has the largest modeled impact. "
                f"Increasing it by 10% {direction} the mid estimate by "
                f"${abs(driver.delta_dollar):,.2f} per unit. "
                f"Check the {label} assumption before relying on the estimate."
            )
        else:
            paragraphs.append(
                "The sensitivity checks found no change at the displayed price precision."
            )

    confidence = f"Input confidence is {estimate.confidence.value.lower()}."
    if estimate.confidence_notes:
        confidence += " " + " ".join(estimate.confidence_notes)
    paragraphs.append(confidence)
    return "\n\n".join(paragraphs)

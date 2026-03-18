"""
explain.py
AI narrative layer for the Should-Cost engine.

CONTRACT (hard rules):
  - AI receives only computed outputs from CostEstimate.
  - AI generates explanation text ONLY.
  - AI never produces, modifies, or overrides any cost number.
  - If the API call fails, the estimate is returned unchanged (narrative = None).
  - The narrative is clearly labeled as AI-generated in all outputs.
"""

from __future__ import annotations
import os
import json
import urllib.request
import urllib.error

from .models import CostEstimate


# ─── PROMPT BUILDER ───────────────────────────────────────────────────────────

def _build_prompt(estimate: CostEstimate) -> str:
    band = estimate.price_band
    bd = estimate.breakdown
    top_drivers = estimate.sensitivity[:3]

    drivers_text = "\n".join(
        f"  - {d.variable}: +{d.delta_pct}% (+${d.delta_dollar}) if it rises 10%"
        for d in top_drivers
    )

    outside = (
        ", ".join(estimate.assumptions_used.outside_process_costs.keys())
        if estimate.assumptions_used.outside_process_costs
        else "None"
    )

    return f"""You are a sourcing analyst writing a plain-language cost explanation for a leadership briefing.

You have been given computed should-cost results for a machined part. Your job is to write a brief, clear narrative that explains:
1. What the price band means and where the range comes from
2. Which cost drivers matter most and why
3. What this implies for a negotiation or sourcing decision

HARD RULES — you must follow these exactly:
- Do not invent, modify, or round any cost numbers. Use only the numbers provided below.
- Do not state a single target price. Discuss the range.
- Do not speculate about supplier margins beyond what is stated.
- Write in plain, professional language. No jargon. No bullet points. Three paragraphs maximum.
- Do not use markdown formatting of any kind. No backticks, no bold, no code spans. Write dollar amounts as plain text like $522.55.
- Do not mention that you are an AI or that this was generated automatically.

COMPUTED RESULTS (do not modify):
Part: {estimate.part_id} — {estimate.part_description}
Material: {estimate.material} | Region: {estimate.region}
Annual Volume: {estimate.annual_volume} | Batch Size: {estimate.batch_size}

Price Band:
  Low:  ${band.low:,.2f}
  Mid:  ${band.mid:,.2f}
  High: ${band.high:,.2f}

Cost Breakdown (mid scenario, per piece):
  Material:             ${bd.material_cost:,.2f}
  Machining:            ${bd.machining_cost:,.2f}
  Setup (amortized):    ${bd.setup_cost_per_piece:,.2f}
  Outside Processes:    ${bd.outside_process_cost:,.2f} ({outside})
  Scrap:                ${bd.scrap_cost:,.2f}
  Overhead:             ${bd.overhead_cost:,.2f}
  Supplier Margin:      ${bd.supplier_margin:,.2f}
  Unit Price (mid):     ${bd.unit_price_mid:,.2f}

Top Cost Drivers (sensitivity: impact of +10% change):
{drivers_text}

Confidence: {estimate.confidence.value}
Confidence Notes: {"; ".join(estimate.confidence_notes)}

Write the narrative now:"""


# ─── API CALL ─────────────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> str | None:
    """
    Call the Anthropic API synchronously.
    Returns the narrative text or None if the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}],
    }

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return None


# ─── PUBLIC FUNCTION ──────────────────────────────────────────────────────────

def add_narrative(estimate: CostEstimate) -> CostEstimate:
    """
    Attach an AI-generated narrative to a CostEstimate.
    Returns the same estimate with ai_narrative populated (or unchanged if API fails).
    Cost numbers are never modified.
    """
    prompt = _build_prompt(estimate)
    narrative = _call_claude(prompt)
    if narrative:
        estimate.ai_narrative = f"[AI-generated narrative — sourcing analyst summary]\n\n{narrative}"
    return estimate

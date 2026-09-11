"""Tier 0 evaluation mechanics — ported directly from
`bidso-labs-evaluation-wireframe-v3.html`'s own JS (`markup()`, `composite()`,
the first-screen pattern rule). Pure functions, no DB access — every value
here is server-computed from inputs the caller already validated, never
trusted from the client, same discipline as `dispatch_price_resolver.py` on
the Playfield side of this engagement.

Each research read is abstracted to a 3-way tier — TOP / MID / BOTTOM —
rather than each criterion's own wireframe-specific label set (e.g.
Differentiation's "No comparable SKU" / "Comparable, stated distinction" /
"Directly comparable, no distinction"). The rule only ever cares about
relative position (top/mid/bottom), never the label text; callers map the
wireframe's actual labels to TOP/MID/BOTTOM before calling this.
"""

from __future__ import annotations

TOP, MID, BOTTOM = "TOP", "MID", "BOTTOM"
_VALID_TIERS = (TOP, MID, BOTTOM)

# --- Detailed-screen band thresholds, from the wireframe's own data-lo/data-hi ---
# (engineering-drawing band; the only band Tier 0 needs — see phased plan)
BAND_ZONE_THRESHOLDS = {
    "ENGINEERING_DRAWING": {"lo": 2.9, "hi": 3.8},
}

# 7 scoring criteria, weights sum to 100 — exact values from the wireframe's
# `.score .w` cells for the engineering-drawing band.
SCORE_WEIGHTS = {
    "market_size": 17,
    "differentiation": 19,
    "manufacturer_concentration": 11,
    "brand_fit": 11,
    "process_fit": 11,
    "technical_feasibility": 13,
    "margin_potential": 18,
}


def markup_band(pct: float) -> str:
    """`band(m)` in the wireframe: m<18 Low, m<43 Med, else High."""
    if pct < 18:
        return "LOW"
    if pct < 43:
        return "MED"
    return "HIGH"


def compute_markup(bom_cost: float, target_price: float) -> tuple[float, str]:
    """`markup(k)` in the wireframe: (price-bom)/bom*100, bom=0 -> 0%."""
    pct = ((target_price - bom_cost) / bom_cost * 100) if bom_cost else 0.0
    return pct, markup_band(pct)


def _validate_tier(name: str, value: str) -> None:
    if value not in _VALID_TIERS:
        raise ValueError(f"{name}: tier must be one of {_VALID_TIERS}, got {value!r}")


def compute_screen_rule(reads: dict) -> str:
    """Pattern rule, wireframe verbatim: "Diff >= mid AND no two bottom
    tiers among Market / Conc / Brand -> go". Diff >= mid means Differentiation
    is not itself at the bottom tier — confirmed by the wireframe's own
    counter-example (MF-0023): Conc=Common (1 bottom tier, itself not
    disqualifying) still fails because Differentiation alone is bottom-tier.

    `reads` shape: {differentiation, market_size, manufacturer_concentration,
    brand_fit} -> {"tier": TOP|MID|BOTTOM, "evidence": str}.
    """
    required = ("differentiation", "market_size", "manufacturer_concentration", "brand_fit")
    missing = [k for k in required if k not in reads]
    if missing:
        raise ValueError(f"Missing research reads: {missing}")
    for k in required:
        _validate_tier(k, reads[k]["tier"])

    diff_ok = reads["differentiation"]["tier"] != BOTTOM
    bottom_count = sum(1 for k in ("market_size", "manufacturer_concentration", "brand_fit") if reads[k]["tier"] == BOTTOM)
    return "GO" if diff_ok and bottom_count < 2 else "NO_GO"


def compute_composite(scores: dict, band: str = "ENGINEERING_DRAWING") -> tuple[float, str]:
    """`composite(k)` in the wireframe: sum(weight*score)/100, zone from the
    band's lo/hi thresholds. `scores` values are 1-5 ints, one per
    `SCORE_WEIGHTS` key.
    """
    missing = [k for k in SCORE_WEIGHTS if k not in scores]
    if missing:
        raise ValueError(f"Missing scores: {missing}")
    for k, v in scores.items():
        if k not in SCORE_WEIGHTS:
            raise ValueError(f"Unknown scoring criterion: {k!r}")
        if not (1 <= v <= 5):
            raise ValueError(f"{k}: score must be 1-5, got {v}")

    total = sum(SCORE_WEIGHTS[k] * scores[k] for k in SCORE_WEIGHTS)
    composite = total / 100

    thresholds = BAND_ZONE_THRESHOLDS.get(band)
    if thresholds is None:
        raise ValueError(f"No zone thresholds configured for band {band!r}")
    lo, hi = thresholds["lo"], thresholds["hi"]
    if composite < lo:
        zone = "DECLINE_DEFAULT"
    elif composite > hi:
        zone = "ADVANCE_DEFAULT"
    else:
        zone = "JUDGEMENT"
    return composite, zone

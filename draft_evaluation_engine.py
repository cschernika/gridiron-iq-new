"""Position-specific draft evaluation for Gridiron IQ."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_WEIGHT_PATH = BASE_DIR / "data" / "draft_position_weights.json"

DISPLAY_NAMES = {
    "projection": "2026 projection",
    "adp_value": "value versus ADP",
    "passing_schedule": "passing strength of schedule",
    "rushing_upside": "rushing upside",
    "offensive_line": "offensive-line quality",
    "receiver_quality": "receiver quality",
    "offensive_pace": "offensive pace",
    "coaching_stability": "coaching stability",
    "injury_outlook": "injury outlook",
    "roster_need": "roster need",
    "projected_touches": "projected touches",
    "goal_line_share": "goal-line share",
    "receiving_role": "receiving role",
    "run_schedule": "run-defense schedule",
    "backfield_competition": "backfield competition",
    "game_script": "expected game script",
    "durability": "durability",
    "target_share": "target share",
    "route_participation": "route participation",
    "quarterback_quality": "quarterback quality",
    "coverage_matchups": "defensive-back and coverage matchups",
    "pass_schedule": "pass-defense schedule",
    "red_zone_role": "red-zone role",
    "yards_after_catch": "yards-after-catch ability",
    "targets_per_route": "targets per route",
    "quarterback_tendency": "quarterback tight-end tendency",
    "schedule": "strength of schedule",
    "positional_scarcity": "positional scarcity",
    "blocking_burden": "receiving opportunity versus blocking burden",
    "offense_quality": "offense quality",
    "scoring_opportunities": "field-goal opportunities",
    "accuracy": "kicking accuracy",
    "dome_weather": "dome and weather outlook",
    "coaching_aggressiveness": "coaching fourth-down tendency",
    "pressure_rate": "pressure rate",
    "sack_upside": "sack upside",
    "takeaway_rate": "takeaway rate",
    "points_allowed": "points-allowed outlook",
    "opponent_qb_schedule": "opposing quarterback schedule",
    "offensive_line_matchups": "opponent offensive-line matchups",
    "overall_schedule": "overall defensive schedule",
    "return_td_upside": "return-touchdown upside",
}


def load_position_weights(path: Path | None = None) -> dict[str, dict[str, float]]:
    target = path or DEFAULT_WEIGHT_PATH
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {
        position.upper(): {
            str(key): float(value)
            for key, value in criteria.items()
        }
        for position, criteria in payload.items()
    }


def _number(value: Any, default: float = 50.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_metric(value: Any) -> float:
    return max(0.0, min(100.0, _number(value)))


def evaluate_player(
    position: str,
    metrics: dict[str, Any],
    *,
    weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    position = str(position or "").upper()
    if position == "DST":
        position = "DEF"

    all_weights = weights or load_position_weights()
    position_weights = all_weights.get(position, {})
    if not position_weights:
        return {
            "position": position,
            "score": 50,
            "grade": "Incomplete",
            "action": "Review manually",
            "breakdown": [],
            "missing_metrics": [],
            "strengths": [],
            "risks": [],
            "coverage": 0,
        }

    total_weight = sum(position_weights.values()) or 1.0
    weighted_points = 0.0
    breakdown = []
    missing_metrics = []

    for criterion, weight in position_weights.items():
        supplied = criterion in metrics and metrics.get(criterion) is not None
        metric_score = clamp_metric(metrics.get(criterion, 50))
        contribution = metric_score * weight / total_weight
        weighted_points += contribution

        if not supplied:
            missing_metrics.append(criterion)

        breakdown.append({
            "criterion": criterion,
            "label": DISPLAY_NAMES.get(
                criterion,
                criterion.replace("_", " ").title(),
            ),
            "score": round(metric_score, 1),
            "weight": round(weight, 1),
            "contribution": round(contribution, 2),
            "data_status": "measured" if supplied else "neutral default",
        })

    breakdown.sort(key=lambda item: item["contribution"], reverse=True)
    final_score = round(weighted_points, 1)

    strengths = [
        item["label"]
        for item in sorted(
            breakdown,
            key=lambda item: item["score"],
            reverse=True,
        )
        if item["score"] >= 70
    ][:4]

    risks = [
        item["label"]
        for item in sorted(
            breakdown,
            key=lambda item: item["score"],
        )
        if item["score"] <= 40
    ][:4]

    if final_score >= 82:
        grade, action = "Elite", "Draft now"
    elif final_score >= 72:
        grade, action = "Strong", "Draft at or slightly before ADP"
    elif final_score >= 62:
        grade, action = "Solid", "Draft near ADP"
    elif final_score >= 52:
        grade, action = "Conditional", "Wait one round"
    else:
        grade, action = "Risky", "Avoid at this price"

    return {
        "position": position,
        "score": final_score,
        "grade": grade,
        "action": action,
        "breakdown": breakdown,
        "missing_metrics": missing_metrics,
        "strengths": strengths,
        "risks": risks,
        "coverage": round(
            100
            * (len(position_weights) - len(missing_metrics))
            / len(position_weights),
            1,
        ),
    }


def baseline_metrics(
    *,
    projection: float = 0,
    previous_points: float = 0,
    adp_value: float = 0,
    roster_need: float = 50,
    scarcity: float = 50,
) -> dict[str, float]:
    projection_score = max(0, min(100, projection / 4.0))
    history_score = max(0, min(100, previous_points / 4.0))
    value_score = max(0, min(100, 50 + adp_value * 3.0))

    return {
        "projection": projection_score,
        "adp_value": value_score,
        "roster_need": max(0, min(100, roster_need)),
        "positional_scarcity": max(0, min(100, scarcity)),
        "projected_touches": projection_score,
        "target_share": history_score,
        "route_participation": history_score,
        "offense_quality": projection_score,
        "scoring_opportunities": projection_score,
    }

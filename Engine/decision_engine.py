"""Draft and weekly lineup decision engine for Gridiron IQ."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from .analytics_engine import AnalyticsEngine
from .matchup_engine import MatchupEngine
from .projection_engine import ProjectionEngine


def _num(data: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = data.get(key, default)
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class DecisionEngine:
    """Combine analytics, projections, scarcity, market price, and roster needs."""

    DEFAULT_DRAFT_WEIGHTS = {
        "value_over_replacement": 0.24,
        "season_projection": 0.16,
        "talent": 0.11,
        "opportunity": 0.13,
        "efficiency": 0.08,
        "environment": 0.06,
        "durability": 0.07,
        "upside": 0.08,
        "floor": 0.04,
        "scarcity": 0.08,
        "roster_need": 0.07,
        "adp_value": 0.08,
    }

    DEFAULT_WEEKLY_WEIGHTS = {
        "projected_points": 0.34,
        "matchup": 0.22,
        "opportunity": 0.14,
        "floor": 0.09,
        "upside": 0.08,
        "health": 0.08,
        "role_certainty": 0.05,
    }

    def __init__(
        self,
        analytics: Optional[AnalyticsEngine] = None,
        matchup: Optional[MatchupEngine] = None,
        projection: Optional[ProjectionEngine] = None,
    ):
        self.analytics = analytics or AnalyticsEngine()
        self.matchup = matchup or MatchupEngine()
        self.projection = projection or ProjectionEngine()

    def draft_score(
        self,
        player: Mapping[str, Any],
        league: Mapping[str, Any],
        roster: Optional[Mapping[str, Any]] = None,
        draft_context: Optional[Mapping[str, Any]] = None,
        team: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        roster = roster or {}
        ctx = draft_context or {}
        components = self.analytics.calculate_components(player, team).as_dict()

        projected_points = _num(player, "season_projected_points", _num(player, "projected_points"))
        replacement_points = _num(ctx, "replacement_points", _num(player, "replacement_points"))
        vor = projected_points - replacement_points
        vor_score = _clamp(50 + vor / max(_num(ctx, "vor_scale", 80), 1) * 50)

        projection_score = _clamp(_num(player, "season_projection_percentile", 50))
        scarcity = self._scarcity_score(player, league, ctx)
        roster_need = self._roster_need_score(player, league, roster)
        adp_value = self._adp_value_score(player, ctx)

        weights = {**self.DEFAULT_DRAFT_WEIGHTS, **league.get("draft_weights", {})}
        values = {
            "value_over_replacement": vor_score,
            "season_projection": projection_score,
            **components,
            "scarcity": scarcity,
            "roster_need": roster_need,
            "adp_value": adp_value,
        }
        score = self._weighted(values, weights)

        availability = _num(ctx, "probability_available_next_pick", 0.50)
        urgency = _clamp((1 - availability) * 100)
        score = _clamp(score * 0.92 + urgency * 0.08)

        confidence = self._draft_confidence(player, ctx, components)
        reasons = self._draft_reasons(values, projected_points, replacement_points, availability)
        recommendation = self._draft_recommendation(score, availability, adp_value)

        return {
            "player_id": player.get("player_id"),
            "player_name": player.get("name"),
            "position": player.get("position"),
            "draft_score": round(score, 2),
            "grade": self._grade(score),
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
            "probability_available_next_pick": round(availability, 3),
            "components": {k: round(v, 2) for k, v in values.items()},
            "reasons": reasons,
        }

    def weekly_score(
        self,
        player: Mapping[str, Any],
        defense: Mapping[str, Any],
        league: Mapping[str, Any],
        context: Optional[Mapping[str, Any]] = None,
        team: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        components = self.analytics.calculate_components(player, team).as_dict()
        matchup = self.matchup.score(player, defense, context)
        projection = self.projection.weekly_projection(
            player, matchup["matchup_score"], league, context
        )

        expected_high = max(_num(context, "position_high_projection", 30), 1)
        projection_score = _clamp(projection["projected_points"] / expected_high * 100)
        values = {
            "projected_points": projection_score,
            "matchup": matchup["matchup_score"],
            "opportunity": components["opportunity"],
            "floor": components["floor"],
            "upside": components["upside"],
            "health": components["durability"],
            "role_certainty": _num(player, "role_certainty_score", 60),
        }
        weights = {**self.DEFAULT_WEEKLY_WEIGHTS, **league.get("weekly_weights", {})}
        score = self._weighted(values, weights)
        confidence = _clamp(
            matchup["confidence"] * 0.35 +
            _num(player, "projection_confidence", 65) * 0.35 +
            _num(player, "role_certainty_score", 60) * 0.30
        )

        return {
            "player_id": player.get("player_id"),
            "player_name": player.get("name"),
            "position": player.get("position"),
            "weekly_score": round(score, 2),
            "grade": self._grade(score),
            "confidence": round(confidence, 2),
            "projection": projection,
            "matchup": matchup,
            "components": {k: round(v, 2) for k, v in values.items()},
            "recommendation": self._weekly_recommendation(score, projection, matchup),
            "reasons": matchup["reasons"] + self._weekly_reasons(components, projection),
        }

    def rank_draft_candidates(
        self,
        players: Iterable[Mapping[str, Any]],
        league: Mapping[str, Any],
        roster: Optional[Mapping[str, Any]] = None,
        contexts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        contexts = contexts or {}
        results = []
        for player in players:
            key = str(player.get("player_id", player.get("name", "")))
            results.append(self.draft_score(player, league, roster, contexts.get(key, {})))
        return sorted(results, key=lambda item: item["draft_score"], reverse=True)

    def rank_weekly_candidates(
        self,
        candidates: Iterable[Mapping[str, Any]],
        league: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        results = []
        for item in candidates:
            results.append(self.weekly_score(
                item["player"],
                item.get("defense", {}),
                league,
                item.get("context", {}),
                item.get("team", {}),
            ))
        return sorted(results, key=lambda item: item["weekly_score"], reverse=True)

    @staticmethod
    def _weighted(values, weights):
        used = [(values[k], w) for k, w in weights.items() if k in values]
        total = sum(w for _, w in used) or 1
        return _clamp(sum(value * weight for value, weight in used) / total)

    @staticmethod
    def _scarcity_score(player, league, ctx):
        position = str(player.get("position", "")).upper()
        starters = league.get("starters", {})
        teams = int(league.get("teams", 12))
        required = float(starters.get(position, 1)) * teams
        remaining = _num(ctx, "remaining_startable_players_at_position", required)
        tier_drop = _num(ctx, "next_tier_drop_percent", 0.10)
        scarcity = _clamp((required / max(remaining, 1)) * 45 + tier_drop * 100 * 0.55)
        if position in {"K", "DST"}:
            scarcity *= 0.45
        return _clamp(scarcity)

    @staticmethod
    def _roster_need_score(player, league, roster):
        position = str(player.get("position", "")).upper()
        starters = league.get("starters", {})
        current = roster.get(position, [])
        required = float(starters.get(position, 1))
        filled = len(current)
        if filled < required:
            return _clamp(82 + (required - filled) * 8)
        bench_depth_target = {"QB": 1, "RB": 4, "WR": 5, "TE": 2, "K": 1, "DST": 1}.get(position, 2)
        return _clamp(65 - max(0, filled - required) * 15 + max(0, bench_depth_target - filled) * 8)

    @staticmethod
    def _adp_value_score(player, ctx):
        current_pick = _num(ctx, "current_overall_pick", 1)
        adp = _num(player, "adp", current_pick)
        adp_sd = max(_num(player, "adp_standard_deviation", 8), 2)
        return _clamp(50 + (adp - current_pick) / adp_sd * 18)

    @staticmethod
    def _draft_confidence(player, ctx, components):
        data_quality = _num(ctx, "data_quality_score", 70)
        projection_conf = _num(player, "projection_confidence", 65)
        role = _num(player, "role_certainty_score", 60)
        durability = components["durability"]
        return _clamp(data_quality * 0.28 + projection_conf * 0.30 + role * 0.24 + durability * 0.18)

    @staticmethod
    def _draft_reasons(values, projected, replacement, availability):
        reasons = []
        if values["value_over_replacement"] >= 65:
            reasons.append(f"Strong value over replacement: {projected - replacement:.1f} projected points.")
        if values["opportunity"] >= 70:
            reasons.append("Projects for an elite or near-elite workload.")
        if values["talent"] >= 70:
            reasons.append("Underlying player-performance metrics rate highly.")
        if values["scarcity"] >= 68:
            reasons.append("Position is becoming scarce relative to league starting requirements.")
        if values["adp_value"] >= 65:
            reasons.append("Available later than market cost suggests.")
        if availability <= 0.30:
            reasons.append("Low probability of surviving to your next selection.")
        if values["durability"] <= 42:
            reasons.append("Meaningful injury or availability risk lowers the grade.")
        return reasons or ["Balanced profile without a single dominant advantage."]

    @staticmethod
    def _weekly_reasons(components, projection):
        reasons = []
        if components["opportunity"] >= 70:
            reasons.append("Usage profile supports a dependable weekly workload.")
        if components["upside"] >= 72:
            reasons.append("Ceiling indicators create strong boom potential.")
        if components["durability"] <= 45:
            reasons.append("Health or workload uncertainty reduces confidence.")
        reasons.append(
            f"Model range: {projection['floor']:.1f} to {projection['ceiling']:.1f} fantasy points."
        )
        return reasons

    @staticmethod
    def _draft_recommendation(score, availability, adp_value):
        if score >= 82:
            return "Draft now"
        if score >= 72 and availability <= 0.40:
            return "Draft now; unlikely to return"
        if score >= 68:
            return "Strong target"
        if score >= 58 and adp_value >= 60:
            return "Value pick"
        if availability >= 0.70:
            return "Wait one round"
        if score < 45:
            return "Pass at current cost"
        return "Consider based on roster build"

    @staticmethod
    def _weekly_recommendation(score, projection, matchup):
        if score >= 78:
            return "Must start"
        if score >= 68:
            return "Start"
        if score >= 58:
            return "Lean start"
        if projection["ceiling"] >= 20 and matchup["matchup_score"] >= 60:
            return "Upside flex"
        if score < 42:
            return "Sit"
        return "Matchup-dependent flex"

    @staticmethod
    def _grade(score):
        if score >= 90: return "Elite"
        if score >= 80: return "A"
        if score >= 70: return "B+"
        if score >= 60: return "B"
        if score >= 50: return "C"
        if score >= 40: return "D"
        return "F"

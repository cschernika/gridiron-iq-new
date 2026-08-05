"""Weekly opponent, coverage, and trench matchup evaluation."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _num(data: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = data.get(key, default)
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class MatchupEngine:
    """Calculate a 0-100 matchup score and explain the largest drivers."""

    def score(
        self,
        player: Mapping[str, Any],
        defense: Mapping[str, Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context or {}
        position = str(player.get("position", "")).upper()

        if position in {"WR", "TE"}:
            components = self._receiver_matchup(player, defense, context)
        elif position == "RB":
            components = self._running_back_matchup(player, defense, context)
        elif position == "QB":
            components = self._quarterback_matchup(player, defense, context)
        elif position in {"K", "DST"}:
            components = self._special_matchup(player, defense, context)
        else:
            components = {"base": 50.0}

        score = sum(v["score"] * v["weight"] for v in components.values())
        total_weight = sum(v["weight"] for v in components.values()) or 1.0
        score = _clamp(score / total_weight)

        weather_penalty = self._weather_penalty(context, position)
        score = _clamp(score - weather_penalty)

        sorted_components = sorted(
            ((name, values["score"], values.get("label", name)) for name, values in components.items()),
            key=lambda row: abs(row[1] - 50),
            reverse=True,
        )
        reasons = []
        for _, component_score, label in sorted_components[:4]:
            if component_score >= 60:
                reasons.append(f"Advantage: {label} ({component_score:.0f}/100)")
            elif component_score <= 40:
                reasons.append(f"Concern: {label} ({component_score:.0f}/100)")
        if weather_penalty >= 4:
            reasons.append(f"Weather lowers the matchup by {weather_penalty:.1f} points")

        confidence = self._confidence(player, defense, context)
        return {
            "matchup_score": round(score, 2),
            "matchup_grade": self.grade(score),
            "confidence": round(confidence, 2),
            "components": {k: round(v["score"], 2) for k, v in components.items()},
            "reasons": reasons or ["No major matchup advantage or disadvantage detected."],
        }

    def _receiver_matchup(self, p, d, c):
        man_rate = _num(d, "man_coverage_rate", 0.30)
        zone_rate = _num(d, "zone_coverage_rate", 0.70)
        single_high = _num(d, "single_high_rate", 0.42)
        two_high = _num(d, "two_high_rate", 0.45)
        three_high = _num(d, "three_high_rate", 0.08)

        man_perf = _num(p, "fantasy_points_per_route_vs_man", _num(p, "yprr_vs_man", 1.6))
        zone_perf = _num(p, "fantasy_points_per_route_vs_zone", _num(p, "yprr_vs_zone", 1.6))
        single_perf = _num(p, "yprr_vs_single_high", 1.7)
        two_high_perf = _num(p, "yprr_vs_two_high", 1.6)
        three_high_perf = _num(p, "yprr_vs_three_high", 1.5)

        coverage_fit_raw = (
            man_rate * man_perf + zone_rate * zone_perf +
            single_high * single_perf * 0.35 + two_high * two_high_perf * 0.35 +
            three_high * three_high_perf * 0.20
        )
        coverage_fit = _clamp((coverage_fit_raw - 0.9) / 2.2 * 100)

        cb = {
            "target_rate": _num(d, "primary_cb_target_rate_allowed", 0.18),
            "catch_rate": _num(d, "primary_cb_catch_rate_allowed", 0.62),
            "yards_per_target": _num(d, "primary_cb_yards_per_target_allowed", 7.2),
            "separation": _num(d, "primary_cb_separation_allowed", 2.5),
            "penalties": _num(d, "primary_cb_penalties_per_game", 0.35),
        }
        cb_score = _clamp(
            (cb["target_rate"] - 0.10) / 0.18 * 25 +
            (cb["catch_rate"] - 0.45) / 0.35 * 25 +
            (cb["yards_per_target"] - 4.5) / 6.0 * 25 +
            (cb["separation"] - 1.5) / 2.5 * 20 +
            min(cb["penalties"] / 1.2 * 5, 5)
        )

        shadow_rate = _num(d, "shadow_rate", 0.0)
        player_alignment_match = _num(c, "alignment_match_probability", 0.75)
        shadow_adjusted = cb_score * player_alignment_match + 50 * (1 - player_alignment_match)
        if shadow_rate < 0.25:
            shadow_adjusted = shadow_adjusted * 0.75 + 50 * 0.25

        pressure_rate = _num(d, "pressure_rate", 0.34)
        qb_pressure_rating = _num(p, "qb_rating_under_pressure", 75)
        pass_protection = _num(c, "pass_protection_score", 50)
        delivery_score = _clamp(pass_protection * 0.55 + qb_pressure_rating * 0.45 - max(0, pressure_rate - 0.33) * 80)

        defense_fp_allowed = _num(d, "fantasy_points_allowed_to_position_percentile", 50)
        pace = _num(c, "expected_play_volume_percentile", 50)
        game = _clamp(defense_fp_allowed * 0.60 + pace * 0.40)

        return {
            "coverage_fit": {"score": coverage_fit, "weight": 0.30, "label": "player production versus expected coverage shells"},
            "cornerback": {"score": shadow_adjusted, "weight": 0.25, "label": "likely cornerback assignment"},
            "delivery": {"score": delivery_score, "weight": 0.20, "label": "quarterback protection and pressure environment"},
            "position_allowance": {"score": defense_fp_allowed, "weight": 0.15, "label": "defense fantasy production allowed to position"},
            "game_environment": {"score": game, "weight": 0.10, "label": "expected game pace and volume"},
        }

    def _running_back_matchup(self, p, d, c):
        box_rate = _num(d, "stacked_box_rate", 0.25)
        yards_before_contact = _num(d, "yards_before_contact_allowed", 1.5)
        adjusted_line_yards = _num(d, "adjusted_line_yards_allowed", 4.2)
        stuff_rate = _num(d, "stuff_rate", 0.20)
        run_score = _clamp(
            (adjusted_line_yards - 3.0) / 2.5 * 45 +
            (yards_before_contact - 0.6) / 2.0 * 35 +
            (0.32 - stuff_rate) / 0.25 * 20 -
            max(0, box_rate - 0.30) * 30
        )
        receiving = _num(d, "rb_receiving_points_allowed_percentile", 50)
        line = _num(c, "run_blocking_score", 50)
        script = _num(c, "positive_game_script_probability", 0.50) * 100
        goal_line = _num(d, "goal_line_td_rate_allowed_percentile", 50)
        return {
            "run_defense": {"score": run_score, "weight": 0.32, "label": "opponent run defense"},
            "receiving": {"score": receiving, "weight": 0.22, "label": "running back receiving matchup"},
            "offensive_line": {"score": line, "weight": 0.18, "label": "offensive line run blocking"},
            "game_script": {"score": script, "weight": 0.18, "label": "projected game script"},
            "goal_line": {"score": goal_line, "weight": 0.10, "label": "goal-line touchdown opportunity"},
        }

    def _quarterback_matchup(self, p, d, c):
        coverage = _num(d, "qb_coverage_matchup_percentile", 50)
        pressure_allowed = 100 - _num(d, "pressure_rate_percentile", 50)
        blitz = _num(d, "blitz_rate", 0.28)
        vs_blitz = _num(p, "qb_rating_vs_blitz_percentile", 50)
        blitz_fit = _clamp(vs_blitz - max(0, blitz - 0.30) * (100 - vs_blitz))
        explosive = 100 - _num(d, "explosive_pass_prevention_percentile", 50)
        rushing = _num(d, "qb_rushing_points_allowed_percentile", 50)
        total = _num(c, "game_total_percentile", 50)
        return {
            "coverage": {"score": coverage, "weight": 0.25, "label": "coverage matchup"},
            "pressure": {"score": pressure_allowed, "weight": 0.22, "label": "pass-rush matchup"},
            "blitz": {"score": blitz_fit, "weight": 0.18, "label": "quarterback performance versus blitz"},
            "explosive": {"score": explosive, "weight": 0.14, "label": "deep passing opportunity"},
            "rushing": {"score": rushing, "weight": 0.11, "label": "quarterback rushing opportunity"},
            "game_total": {"score": total, "weight": 0.10, "label": "projected scoring environment"},
        }

    def _special_matchup(self, p, d, c):
        position = str(p.get("position", "")).upper()
        if position == "K":
            return {
                "attempts": {"score": _num(c, "field_goal_opportunity_percentile", 50), "weight": 0.55, "label": "field-goal opportunity"},
                "conditions": {"score": _num(c, "kicking_conditions_score", 50), "weight": 0.25, "label": "kicking conditions"},
                "accuracy": {"score": _num(p, "accuracy_percentile", 50), "weight": 0.20, "label": "kicker accuracy"},
            }
        return {
            "turnovers": {"score": _num(d, "opponent_turnover_prone_percentile", 50), "weight": 0.35, "label": "opponent turnover risk"},
            "sacks": {"score": _num(d, "opponent_sack_allowed_percentile", 50), "weight": 0.35, "label": "sack opportunity"},
            "points": {"score": 100 - _num(c, "opponent_implied_points_percentile", 50), "weight": 0.30, "label": "opponent implied points"},
        }

    @staticmethod
    def _weather_penalty(context: Mapping[str, Any], position: str) -> float:
        wind = _num(context, "wind_mph", 0)
        precipitation = _num(context, "precipitation_probability", 0)
        temperature = _num(context, "temperature_f", 65)
        dome = bool(context.get("dome", False))
        if dome:
            return 0.0
        penalty = max(0, wind - 15) * (0.45 if position in {"QB", "WR", "TE", "K"} else 0.18)
        penalty += max(0, precipitation - 0.55) * 8
        if temperature < 25:
            penalty += (25 - temperature) * 0.12
        return min(penalty, 18)

    @staticmethod
    def _confidence(player, defense, context):
        sample = min(_num(player, "routes_or_touches_sample", 100) / 350 * 100, 100)
        role_certainty = _num(player, "role_certainty_score", 60)
        assignment_certainty = _num(context, "assignment_certainty_score", 55)
        data_quality = _num(context, "data_quality_score", 70)
        return _clamp(sample * 0.22 + role_certainty * 0.30 + assignment_certainty * 0.20 + data_quality * 0.28)

    @staticmethod
    def grade(score: float) -> str:
        if score >= 85: return "A+"
        if score >= 78: return "A"
        if score >= 70: return "B+"
        if score >= 63: return "B"
        if score >= 55: return "C+"
        if score >= 45: return "C"
        if score >= 37: return "D"
        return "F"

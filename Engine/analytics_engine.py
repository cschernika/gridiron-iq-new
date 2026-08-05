"""Feature engineering for Gridiron IQ.

The AnalyticsEngine converts raw player/team statistics into normalized,
position-aware component scores. It intentionally accepts dictionaries so it
can be used with SQLAlchemy rows, pandas records, JSON APIs, or cached data.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, Mapping, Optional


def _num(data: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = data.get(key, default)
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ComponentScores:
    talent: float
    opportunity: float
    efficiency: float
    environment: float
    durability: float
    upside: float
    floor: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "talent": round(self.talent, 2),
            "opportunity": round(self.opportunity, 2),
            "efficiency": round(self.efficiency, 2),
            "environment": round(self.environment, 2),
            "durability": round(self.durability, 2),
            "upside": round(self.upside, 2),
            "floor": round(self.floor, 2),
        }


class AnalyticsEngine:
    """Calculate position-specific player analytics on a 0-100 scale."""

    POSITION_WEIGHTS = {
        "QB": {
            "talent": {"epa_per_play": 0.22, "cpoe": 0.16, "big_time_throw_rate": 0.14,
                       "pressure_to_sack_rate_inv": 0.12, "pass_yards_per_attempt": 0.16,
                       "rush_yards_per_game": 0.10, "td_rate": 0.10},
            "opportunity": {"dropbacks_per_game": 0.38, "neutral_pass_rate": 0.25,
                            "red_zone_pass_attempts_per_game": 0.20, "designed_rushes_per_game": 0.17},
            "efficiency": {"fantasy_points_per_dropback": 0.35, "epa_per_play": 0.30,
                           "success_rate": 0.20, "explosive_pass_rate": 0.15},
        },
        "RB": {
            "talent": {"yards_after_contact_per_attempt": 0.25, "missed_tackles_forced_per_touch": 0.22,
                       "explosive_run_rate": 0.18, "yards_per_route_run": 0.15,
                       "rush_yards_over_expected_per_attempt": 0.20},
            "opportunity": {"rush_share": 0.26, "target_share": 0.18, "snap_share": 0.20,
                            "route_participation": 0.12, "red_zone_opportunity_share": 0.24},
            "efficiency": {"fantasy_points_per_opportunity": 0.28, "yards_per_touch": 0.22,
                           "success_rate": 0.18, "yards_after_contact_per_attempt": 0.18,
                           "yards_per_route_run": 0.14},
        },
        "WR": {
            "talent": {"yards_per_route_run": 0.24, "target_separation": 0.14,
                       "open_score": 0.13, "catch_rate_over_expected": 0.15,
                       "yards_after_catch_over_expected": 0.12, "route_win_rate": 0.22},
            "opportunity": {"target_share": 0.25, "air_yards_share": 0.22, "route_participation": 0.19,
                            "first_read_target_share": 0.19, "red_zone_target_share": 0.15},
            "efficiency": {"fantasy_points_per_route": 0.25, "yards_per_route_run": 0.26,
                           "racr": 0.16, "wopr": 0.18, "explosive_reception_rate": 0.15},
        },
        "TE": {
            "talent": {"yards_per_route_run": 0.25, "route_win_rate": 0.18,
                       "target_separation": 0.13, "contested_catch_rate": 0.14,
                       "yards_after_catch_per_reception": 0.15, "catch_rate_over_expected": 0.15},
            "opportunity": {"target_share": 0.25, "route_participation": 0.25,
                            "first_read_target_share": 0.18, "red_zone_target_share": 0.20,
                            "slot_rate": 0.12},
            "efficiency": {"fantasy_points_per_route": 0.26, "yards_per_route_run": 0.26,
                           "touchdowns_per_target": 0.13, "catch_rate": 0.16,
                           "yards_per_target": 0.19},
        },
        "K": {
            "talent": {"field_goal_accuracy": 0.50, "long_field_goal_accuracy": 0.30,
                       "extra_point_accuracy": 0.20},
            "opportunity": {"field_goal_attempts_per_game": 0.50, "extra_point_attempts_per_game": 0.25,
                            "team_drives_per_game": 0.25},
            "efficiency": {"fantasy_points_per_attempt": 0.60, "field_goal_accuracy": 0.40},
        },
        "DST": {
            "talent": {"pressure_rate": 0.22, "sack_rate": 0.20, "turnover_rate": 0.22,
                       "epa_allowed_per_play_inv": 0.20, "explosive_play_rate_allowed_inv": 0.16},
            "opportunity": {"opponent_dropbacks_per_game": 0.38, "opponent_turnover_prone_rate": 0.32,
                            "home_game": 0.10, "favored_probability": 0.20},
            "efficiency": {"fantasy_points_per_game": 0.40, "pressure_rate": 0.20,
                           "sack_rate": 0.20, "turnover_rate": 0.20},
        },
    }

    # Expected practical ranges. Values are scaled within these ranges.
    RANGES = {
        "epa_per_play": (-0.25, 0.35), "cpoe": (-8, 10), "big_time_throw_rate": (0.01, 0.10),
        "pressure_to_sack_rate_inv": (0.65, 0.95), "pass_yards_per_attempt": (5.0, 9.5),
        "rush_yards_per_game": (0, 70), "td_rate": (0.01, 0.09), "dropbacks_per_game": (20, 48),
        "neutral_pass_rate": (0.40, 0.72), "red_zone_pass_attempts_per_game": (1, 8),
        "designed_rushes_per_game": (0, 11), "fantasy_points_per_dropback": (0.25, 0.75),
        "success_rate": (0.30, 0.60), "explosive_pass_rate": (0.04, 0.18),
        "yards_after_contact_per_attempt": (1.5, 4.5), "missed_tackles_forced_per_touch": (0.05, 0.35),
        "explosive_run_rate": (0.02, 0.18), "yards_per_route_run": (0.5, 3.5),
        "rush_yards_over_expected_per_attempt": (-1.0, 1.8), "rush_share": (0.15, 0.85),
        "target_share": (0.02, 0.36), "snap_share": (0.25, 0.95), "route_participation": (0.20, 0.95),
        "red_zone_opportunity_share": (0.05, 0.85), "fantasy_points_per_opportunity": (0.25, 1.35),
        "yards_per_touch": (3.0, 8.5), "yards_per_route_run": (0.5, 3.5),
        "target_separation": (0.5, 4.5), "open_score": (30, 95), "catch_rate_over_expected": (-12, 15),
        "yards_after_catch_over_expected": (-2, 5), "route_win_rate": (0.25, 0.65),
        "air_yards_share": (0.05, 0.50), "first_read_target_share": (0.03, 0.45),
        "red_zone_target_share": (0.02, 0.45), "fantasy_points_per_route": (0.10, 0.70),
        "racr": (0.35, 1.25), "wopr": (0.15, 0.85), "explosive_reception_rate": (0.04, 0.30),
        "contested_catch_rate": (0.20, 0.80), "yards_after_catch_per_reception": (2.0, 9.0),
        "slot_rate": (0.0, 0.90), "touchdowns_per_target": (0.0, 0.18), "catch_rate": (0.45, 0.85),
        "yards_per_target": (4.0, 12.0), "field_goal_accuracy": (0.65, 1.0),
        "long_field_goal_accuracy": (0.40, 0.95), "extra_point_accuracy": (0.85, 1.0),
        "field_goal_attempts_per_game": (0.8, 3.2), "extra_point_attempts_per_game": (1.0, 4.0),
        "team_drives_per_game": (8, 14), "fantasy_points_per_attempt": (1.5, 4.0),
        "pressure_rate": (0.20, 0.48), "sack_rate": (0.03, 0.12), "turnover_rate": (0.04, 0.20),
        "epa_allowed_per_play_inv": (0.35, 0.85), "explosive_play_rate_allowed_inv": (0.55, 0.90),
        "opponent_dropbacks_per_game": (24, 48), "opponent_turnover_prone_rate": (0.04, 0.22),
        "home_game": (0, 1), "favored_probability": (0.1, 0.9), "fantasy_points_per_game": (2, 14),
    }

    @classmethod
    def scale_metric(cls, key: str, value: float) -> float:
        low, high = cls.RANGES.get(key, (0.0, 1.0))
        if high == low:
            return 50.0
        return _clamp((value - low) / (high - low) * 100.0)

    @classmethod
    def weighted_score(cls, data: Mapping[str, Any], weights: Mapping[str, float]) -> float:
        total = 0.0
        used = 0.0
        for key, weight in weights.items():
            if key in data and data.get(key) is not None:
                total += cls.scale_metric(key, _num(data, key)) * weight
                used += weight
        return 50.0 if used == 0 else _clamp(total / used)

    def calculate_components(
        self,
        player: Mapping[str, Any],
        team: Optional[Mapping[str, Any]] = None,
        position_baseline: Optional[Mapping[str, Any]] = None,
    ) -> ComponentScores:
        position = str(player.get("position", "")).upper()
        cfg = self.POSITION_WEIGHTS.get(position, self.POSITION_WEIGHTS["WR"])

        talent = self.weighted_score(player, cfg["talent"])
        opportunity = self.weighted_score(player, cfg["opportunity"])
        efficiency = self.weighted_score(player, cfg["efficiency"])

        team = team or {}
        environment = self._environment_score(player, team)
        durability = self._durability_score(player)
        upside = self._upside_score(player, talent, opportunity, environment)
        floor = self._floor_score(player, opportunity, efficiency, durability)

        return ComponentScores(talent, opportunity, efficiency, environment, durability, upside, floor)

    def _environment_score(self, player: Mapping[str, Any], team: Mapping[str, Any]) -> float:
        offense_epa = _num(team, "offense_epa_per_play", _num(player, "team_offense_epa_per_play", 0))
        implied_points = _num(team, "implied_points", _num(player, "team_implied_points", 22))
        pace = _num(team, "seconds_per_snap", 28.5)
        qb_quality = _num(team, "qb_quality_score", _num(player, "qb_quality_score", 50))
        line_score = _num(team, "offensive_line_score", _num(player, "offensive_line_score", 50))
        coaching = _num(team, "play_caller_score", 50)

        offense = self.scale_metric("epa_per_play", offense_epa)
        implied = _clamp((implied_points - 14) / 20 * 100)
        pace_score = _clamp((33 - pace) / 9 * 100)
        return _clamp(
            offense * 0.25 + implied * 0.22 + pace_score * 0.13 +
            qb_quality * 0.17 + line_score * 0.13 + coaching * 0.10
        )

    @staticmethod
    def _durability_score(player: Mapping[str, Any]) -> float:
        games_missed = _num(player, "games_missed_last_2_years", 0)
        injury_risk = _num(player, "injury_risk", 0.20)
        age_risk = _num(player, "age_curve_risk", 0.15)
        current_health = _num(player, "health_score", 100)
        workload_risk = _num(player, "workload_risk", 0.15)
        return _clamp(
            current_health * 0.42 +
            (100 - min(games_missed / 16 * 100, 100)) * 0.20 +
            (1 - injury_risk) * 100 * 0.20 +
            (1 - age_risk) * 100 * 0.10 +
            (1 - workload_risk) * 100 * 0.08
        )

    @staticmethod
    def _upside_score(player: Mapping[str, Any], talent: float, opportunity: float, environment: float) -> float:
        boom_rate = _num(player, "boom_rate", 0.20) * 100
        explosive = _num(player, "explosive_play_percentile", 50)
        role_growth = _num(player, "role_growth_score", 50)
        uncertainty_bonus = min(_num(player, "projection_standard_deviation", 0) * 4, 20)
        return _clamp(
            talent * 0.25 + opportunity * 0.22 + environment * 0.18 +
            boom_rate * 0.15 + explosive * 0.10 + role_growth * 0.10 + uncertainty_bonus
        )

    @staticmethod
    def _floor_score(player: Mapping[str, Any], opportunity: float, efficiency: float, durability: float) -> float:
        weekly_consistency = _num(player, "weekly_consistency_score", 50)
        bust_rate = _num(player, "bust_rate", 0.25) * 100
        guaranteed_volume = _num(player, "guaranteed_volume_score", opportunity)
        return _clamp(
            opportunity * 0.26 + efficiency * 0.16 + durability * 0.20 +
            weekly_consistency * 0.20 + guaranteed_volume * 0.18 - bust_rate * 0.12
        )

    @staticmethod
    def z_scores(records: Iterable[Mapping[str, Any]], metric: str) -> Dict[str, float]:
        rows = list(records)
        values = [_num(row, metric) for row in rows]
        if not values:
            return {}
        avg = mean(values)
        sd = pstdev(values)
        if sd == 0:
            return {str(row.get("player_id", row.get("name", i))): 0.0 for i, row in enumerate(rows)}
        return {
            str(row.get("player_id", row.get("name", i))): (_num(row, metric) - avg) / sd
            for i, row in enumerate(rows)
        }

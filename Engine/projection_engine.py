"""Season and weekly fantasy point projections."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _num(data: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = data.get(key, default)
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


class ProjectionEngine:
    """Project fantasy points from volume, efficiency, scoring, and matchup."""

    DEFAULT_SCORING = {
        "pass_yards": 0.04, "pass_td": 4.0, "interception": -2.0,
        "rush_yards": 0.10, "rush_td": 6.0,
        "reception": 1.0, "rec_yards": 0.10, "rec_td": 6.0,
        "fumble_lost": -2.0,
        "fg_0_39": 3.0, "fg_40_49": 4.0, "fg_50_plus": 5.0, "xp": 1.0,
    }

    def weekly_projection(
        self,
        player: Mapping[str, Any],
        matchup_score: float = 50.0,
        league_settings: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        scoring = {**self.DEFAULT_SCORING, **(league_settings or {}).get("scoring", {})}
        context = context or {}
        position = str(player.get("position", "")).upper()

        if position == "QB":
            raw = self._qb_points(player, scoring)
        elif position == "RB":
            raw = self._rb_points(player, scoring)
        elif position in {"WR", "TE"}:
            raw = self._receiver_points(player, scoring)
        elif position == "K":
            raw = self._kicker_points(player, scoring)
        elif position == "DST":
            raw = _num(player, "baseline_fantasy_points", 6.0)
        else:
            raw = _num(player, "baseline_fantasy_points", 0.0)

        matchup_multiplier = 1.0 + (matchup_score - 50.0) / 250.0
        injury_multiplier = _num(context, "expected_snap_multiplier", 1.0)
        role_multiplier = _num(context, "role_multiplier", 1.0)
        game_multiplier = _num(context, "game_environment_multiplier", 1.0)
        projected = max(0.0, raw * matchup_multiplier * injury_multiplier * role_multiplier * game_multiplier)

        volatility = _num(player, "weekly_volatility", max(2.5, projected * 0.28))
        floor = max(0.0, projected - 1.15 * volatility)
        ceiling = projected + 1.45 * volatility

        return {
            "projected_points": round(projected, 2),
            "floor": round(floor, 2),
            "ceiling": round(ceiling, 2),
            "baseline_points": round(raw, 2),
            "matchup_multiplier": round(matchup_multiplier, 3),
        }

    def season_projection(
        self,
        weekly: Mapping[str, Any],
        games_remaining: int,
        availability_probability: float = 0.94,
    ) -> Dict[str, float]:
        points = _num(weekly, "projected_points")
        floor = _num(weekly, "floor")
        ceiling = _num(weekly, "ceiling")
        expected_games = max(0, games_remaining) * max(0, min(1, availability_probability))
        return {
            "expected_games": round(expected_games, 2),
            "projected_points": round(points * expected_games, 2),
            "floor": round(floor * expected_games, 2),
            "ceiling": round(ceiling * expected_games, 2),
        }

    @staticmethod
    def _qb_points(p, s):
        return (
            _num(p, "projected_pass_yards", _num(p, "pass_yards_per_game")) * s["pass_yards"] +
            _num(p, "projected_pass_tds", _num(p, "pass_tds_per_game")) * s["pass_td"] +
            _num(p, "projected_interceptions", _num(p, "interceptions_per_game")) * s["interception"] +
            _num(p, "projected_rush_yards", _num(p, "rush_yards_per_game")) * s["rush_yards"] +
            _num(p, "projected_rush_tds", _num(p, "rush_tds_per_game")) * s["rush_td"] -
            _num(p, "projected_fumbles_lost", _num(p, "fumbles_lost_per_game")) * abs(s["fumble_lost"])
        )

    @staticmethod
    def _rb_points(p, s):
        return (
            _num(p, "projected_rush_yards", _num(p, "rush_yards_per_game")) * s["rush_yards"] +
            _num(p, "projected_rush_tds", _num(p, "rush_tds_per_game")) * s["rush_td"] +
            _num(p, "projected_receptions", _num(p, "receptions_per_game")) * s["reception"] +
            _num(p, "projected_rec_yards", _num(p, "rec_yards_per_game")) * s["rec_yards"] +
            _num(p, "projected_rec_tds", _num(p, "rec_tds_per_game")) * s["rec_td"]
        )

    @staticmethod
    def _receiver_points(p, s):
        return (
            _num(p, "projected_receptions", _num(p, "receptions_per_game")) * s["reception"] +
            _num(p, "projected_rec_yards", _num(p, "rec_yards_per_game")) * s["rec_yards"] +
            _num(p, "projected_rec_tds", _num(p, "rec_tds_per_game")) * s["rec_td"] +
            _num(p, "projected_rush_yards", _num(p, "rush_yards_per_game")) * s["rush_yards"] +
            _num(p, "projected_rush_tds", _num(p, "rush_tds_per_game")) * s["rush_td"]
        )

    @staticmethod
    def _kicker_points(p, s):
        return (
            _num(p, "fg_0_39_per_game") * s["fg_0_39"] +
            _num(p, "fg_40_49_per_game") * s["fg_40_49"] +
            _num(p, "fg_50_plus_per_game") * s["fg_50_plus"] +
            _num(p, "xp_per_game") * s["xp"]
        )

"""Gridiron IQ Draft Intelligence Engine v1.

One recommendation model for live drafts and mock drafts.

The engine deliberately keeps ADP as a *market signal*, not the dominant
signal.  It scores each remaining player using production/quality, projected
fantasy scoring, the user's roster needs, the league's lineup/scoring rules,
role/usage, the strength and weakness of the remaining position group, and the
risk that the player will disappear before the user's next selection.

The module is pure Python and has no Flask/network dependencies so it can be
unit-tested independently of ESPN/Yahoo connections.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import exp
from statistics import mean
from typing import Any, Iterable

ENGINE_VERSION = "draft-intelligence-v2-roster-completion"

BASE_WEIGHTS = {
    "scoring_potential": 0.22,
    "player_quality": 0.20,
    "roster_need": 0.18,
    "league_fit": 0.10,
    "group_urgency": 0.14,
    "usage_role": 0.08,
    "market_value": 0.04,
    "next_pick_urgency": 0.04,
}

FLEX_POSITIONS = {"RB", "WR", "TE"}
SUPERFLEX_POSITIONS = {"QB", "RB", "WR", "TE"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if number == number else default
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, _num(value)))


def _pos(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "DEF" if text in {"DST", "D/ST"} else "RB" if text == "FB" else text


def _percentile_scores(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    """Return a 25-99 score ranked *within the current position pool*.

    Because the comparison set is the players who are still available, a good
    late-round starter can still receive an excellent scoring-potential grade.
    """
    by_position: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        by_position[_pos(row.get("pos"))].append((str(row.get("name")), _num(row.get(field))))

    output: dict[str, float] = {}
    for _, values in by_position.items():
        ordered = sorted(values, key=lambda item: item[1])
        n = len(ordered)
        if not n:
            continue
        for index, (name, value) in enumerate(ordered):
            if value <= 0:
                score = 25.0
            elif n == 1:
                score = 85.0
            else:
                score = 35.0 + (64.0 * index / (n - 1))
            output[name] = round(_clamp(score, 25, 99), 1)
    return output


def _stage_weights(round_no: int, total_rounds: int) -> dict[str, float]:
    weights = dict(BASE_WEIGHTS)
    total_rounds = max(6, int(total_rounds or 15))
    round_no = max(1, int(round_no or 1))

    # Early: secure true difference-makers.  Need matters, but should not force
    # a mediocre player over an elite one simply because a slot is open.
    if round_no <= 3:
        weights["player_quality"] += 0.03
        weights["scoring_potential"] += 0.03
        weights["roster_need"] -= 0.02
        weights["group_urgency"] -= 0.01
        weights["usage_role"] -= 0.01
        weights["market_value"] -= 0.01
        weights["next_pick_urgency"] -= 0.01
    # Late: role, opportunity and usable depth matter more than raw season rank.
    elif round_no >= max(9, total_rounds - 5):
        weights["player_quality"] -= 0.03
        weights["scoring_potential"] -= 0.02
        weights["roster_need"] -= 0.01
        weights["league_fit"] -= 0.01
        weights["usage_role"] += 0.04
        weights["group_urgency"] += 0.01
        weights["market_value"] += 0.01
        weights["next_pick_urgency"] += 0.01

    total = sum(max(0.0, value) for value in weights.values()) or 1.0
    return {key: max(0.0, value) / total for key, value in weights.items()}


def _league_starters(league: dict[str, Any]) -> dict[str, int]:
    raw = league.get("starters") or league.get("roster_slots") or {}
    starters: dict[str, int] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            key = str(key or "").upper().replace("D/ST", "DEF").replace("DST", "DEF")
            try:
                starters[key] = max(0, int(value or 0))
            except (TypeError, ValueError):
                continue
    if not starters:
        starters = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}
    return starters


def _roster_counts(roster: Iterable[dict[str, Any]]) -> Counter:
    return Counter(_pos(player.get("pos") or player.get("position")) for player in roster)


def _starter_completion(roster: list[dict[str, Any]], league: dict[str, Any]) -> dict[str, Any]:
    """Return lineup-completion status for direct starters, FLEX and Superflex.

    This is used as a draft safety rail: as the number of selections remaining
    approaches the number of required lineup slots still open, candidates that
    cannot fill a required slot are sharply deprioritized.
    """
    counts = _roster_counts(roster)
    starters = _league_starters(league)
    actual_positions = ("QB", "RB", "WR", "TE", "K", "DEF")
    direct_missing = {
        pos: max(0, int(starters.get(pos, 0)) - int(counts.get(pos, 0)))
        for pos in actual_positions
    }

    # Players beyond direct RB/WR/TE requirements can fill FLEX.
    flex_required = int(starters.get("FLEX", 0) + starters.get("W/R/T", 0))
    flex_extras = sum(
        max(0, int(counts.get(pos, 0)) - int(starters.get(pos, 0)))
        for pos in FLEX_POSITIONS
    )
    flex_filled = min(flex_required, flex_extras)
    flex_missing = max(0, flex_required - flex_filled)

    # Superflex can use a spare QB or a FLEX-eligible player not already
    # consumed by a FLEX slot. This approximation is intentionally conservative.
    sf_required = int(starters.get("SUPERFLEX", 0) + starters.get("OP", 0))
    qb_extras = max(0, int(counts.get("QB", 0)) - int(starters.get("QB", 0)))
    flex_extras_after_flex = max(0, flex_extras - flex_filled)
    sf_filled = min(sf_required, qb_extras + flex_extras_after_flex)
    sf_missing = max(0, sf_required - sf_filled)

    required_open = sum(direct_missing.values()) + flex_missing + sf_missing
    can_fill: dict[str, bool] = {}
    for pos in actual_positions:
        direct_open = direct_missing.get(pos, 0) > 0
        flex_open = pos in FLEX_POSITIONS and flex_missing > 0 and counts.get(pos, 0) >= starters.get(pos, 0)
        sf_open = pos in SUPERFLEX_POSITIONS and sf_missing > 0 and counts.get(pos, 0) >= starters.get(pos, 0)
        can_fill[pos] = bool(direct_open or flex_open or sf_open)

    return {
        "counts": counts,
        "starters": starters,
        "direct_missing": direct_missing,
        "flex_required": flex_required,
        "flex_filled": flex_filled,
        "flex_missing": flex_missing,
        "superflex_required": sf_required,
        "superflex_filled": sf_filled,
        "superflex_missing": sf_missing,
        "required_open": required_open,
        "can_fill": can_fill,
    }


def _roster_need_score(
    position: str,
    roster: list[dict[str, Any]],
    league: dict[str, Any],
    round_no: int,
    total_rounds: int,
) -> float:
    position = _pos(position)
    completion = _starter_completion(roster, league)
    counts = completion["counts"]
    starters = completion["starters"]
    direct = int(starters.get(position, 0))
    current = int(counts.get(position, 0))
    flex = int(completion.get("flex_required", 0))
    superflex = int(completion.get("superflex_required", 0))

    roster_size = int(_num(league.get("roster_size"), total_rounds) or total_rounds)
    remaining_picks = max(0, roster_size - len(roster))
    required_open = int(completion.get("required_open", 0))
    can_fill_required = bool(completion.get("can_fill", {}).get(position))

    # Hard completion mode. If every remaining selection is needed to satisfy
    # the lineup rules, do not recommend a luxury/depth pick that would make a
    # complete roster mathematically impossible.
    if required_open > 0 and remaining_picks <= required_open:
        return 99.0 if can_fill_required else 5.0

    if position in {"K", "DEF"}:
        if direct <= 0:
            return 15.0
        if current >= direct:
            return 15.0
        if required_open and remaining_picks <= required_open + 2:
            return 98.0
        # Avoid paying for replaceable positions too early, but still force
        # them late enough to complete the configured roster.
        return 90.0 if round_no >= max(8, total_rounds - 2) else 8.0

    open_direct = max(0, direct - current)
    if open_direct >= 2:
        score = 98.0
    elif open_direct == 1:
        score = 91.0
    else:
        score = 48.0

    if position in FLEX_POSITIONS and flex and completion.get("flex_missing", 0) > 0:
        score = max(score, 82.0)

    if position in SUPERFLEX_POSITIONS and superflex and completion.get("superflex_missing", 0) > 0:
        score = max(score, 86.0)
        if position == "QB" and current < 2:
            score = max(score, 94.0)

    # Two-pick warning zone: required slots become a major priority before the
    # app reaches the final forced-selection state.
    if required_open and remaining_picks <= required_open + 2:
        if can_fill_required:
            score = max(score, 96.0)
        elif open_direct == 0:
            score = min(score, 34.0)

    # Once starters are filled, use user/league position targets when supplied;
    # otherwise retain practical RB/WR-heavy depth targets.
    targets = league.get("position_targets") if isinstance(league.get("position_targets"), dict) else {}
    target = int(_num(targets.get(position), 0)) if targets else 0
    if target <= 0:
        target = direct + (2 if position in {"RB", "WR"} else 1)

    if open_direct == 0 and not can_fill_required:
        if current < target:
            score = max(score, 62.0 if round_no <= 9 else 68.0)
        elif current >= target:
            score = min(score, 34.0)

    return round(_clamp(score), 1)

def _league_fit_score(position: str, player: dict[str, Any], league: dict[str, Any]) -> float:
    position = _pos(position)
    score = 74.0
    scoring = str(league.get("scoring") or league.get("scoring_label") or "").upper()
    starters = _league_starters(league)
    teams = max(8, int(_num(league.get("teams") or league.get("team_count"), 12)))
    role = str(player.get("role_label") or player.get("usage_role") or "").upper()

    full_ppr = "FULL" in scoring or ("PPR" in scoring and "HALF" not in scoring)
    half_ppr = "HALF" in scoring
    if full_ppr:
        score += {"WR": 8, "TE": 6, "RB": 4}.get(position, 0)
        if position == "RB" and any(token in role for token in ("PASS", "3RD", "THIRD", "RECEIV")):
            score += 5
    elif half_ppr:
        score += {"WR": 4, "TE": 3, "RB": 3}.get(position, 0)
    else:
        score += {"RB": 7, "WR": -2, "TE": -1}.get(position, 0)

    if starters.get("WR", 0) >= 3 and position == "WR":
        score += 8
    if starters.get("RB", 0) >= 3 and position == "RB":
        score += 8
    if starters.get("TE", 0) >= 2 and position == "TE":
        score += 12
    if (starters.get("SUPERFLEX", 0) or starters.get("OP", 0) or starters.get("QB", 0) >= 2) and position == "QB":
        score += 22
    if (starters.get("FLEX", 0) or starters.get("W/R/T", 0)) and position in FLEX_POSITIONS:
        score += 4

    if teams >= 14 and position in {"RB", "WR", "TE", "QB"}:
        score += 4
    elif teams <= 10 and position == "QB" and not (starters.get("SUPERFLEX", 0) or starters.get("QB", 0) >= 2):
        score -= 5

    return round(_clamp(score), 1)


def _market_grade(adp: float, overall_pick: int) -> tuple[float, float]:
    adp = _num(adp, 999.0)
    if not 0 < adp < 999:
        return 55.0, 0.0
    value = float(overall_pick) - adp  # positive = player fell past ADP
    if value >= 0:
        grade = 78.0 + min(21.0, value * 1.10)
    else:
        reach = abs(value)
        grade = 78.0 - min(60.0, reach * 1.55 + max(0.0, reach - 12) * 0.70)
    return round(_clamp(grade), 1), round(value, 1)


def survival_probability(adp: Any, next_overall: int | None) -> int:
    adp = _num(adp, 999.0)
    if not next_overall or not 0 < adp < 999:
        return 25
    distance = int(next_overall) - adp
    # If ADP is later than the user's next pick, survival can be quite high.
    if distance <= 0:
        return int(round(_clamp(78 + abs(distance) * 1.3, 30, 95)))
    return int(round(_clamp(82 * exp(-distance / 18.0), 5, 92)))


def _candidate_core_score(player: dict[str, Any], projection_pct: dict[str, float], history_pct: dict[str, float]) -> float:
    name = str(player.get("name"))
    scoring = _num(player.get("scoring_score") or player.get("scoring_potential"), projection_pct.get(name, 50))
    usage = _num(player.get("usage_score"), 55)
    history = _num(player.get("history_score"), history_pct.get(name, 50))
    supplied_quality = player.get("quality_score") or player.get("player_quality")
    if supplied_quality is not None:
        quality = _num(supplied_quality, 50)
    else:
        quality = scoring * 0.48 + usage * 0.32 + history * 0.20
    return round(_clamp(quality), 1)


def analyze_position_groups(
    available: list[dict[str, Any]],
    *,
    league: dict[str, Any],
    recent_picks: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    recent_picks = recent_picks or []
    teams = max(8, int(_num(league.get("teams") or league.get("team_count"), 12)))
    starters = _league_starters(league)
    recent_window = recent_picks[-10:]
    recent_counts = Counter(_pos(p.get("pos") or p.get("position")) for p in recent_window)
    drafted_counts = Counter(_pos(p.get("pos") or p.get("position")) for p in recent_picks)

    projection_pct = _percentile_scores(available, "projection")
    history_pct = _percentile_scores(available, "previous_points")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in available:
        item = dict(player)
        item["_core"] = _candidate_core_score(item, projection_pct, history_pct)
        groups[_pos(item.get("pos"))].append(item)

    result: dict[str, dict[str, Any]] = {}
    for position, players in groups.items():
        players.sort(key=lambda item: (item["_core"], -_num(item.get("adp"), 999)), reverse=True)
        top_scores = [item["_core"] for item in players[:8]]
        depth_score = mean(top_scores) if top_scores else 45.0
        starter_quality = sum(1 for item in players if item["_core"] >= 72)
        elite_remaining = sum(1 for item in players if item["_core"] >= 86)

        direct = int(starters.get(position, 0))
        if position in FLEX_POSITIONS:
            direct += int(round((starters.get("FLEX", 0) + starters.get("W/R/T", 0)) / 3.0))
        if position == "QB" and (starters.get("SUPERFLEX", 0) or starters.get("OP", 0)):
            direct += 1
        league_demand = max(1, teams * max(1, direct))
        demand_remaining = max(1, league_demand - drafted_counts.get(position, 0))
        supply_ratio = starter_quality / demand_remaining

        # Measure the quality drop after the current best cluster.
        tier_values: dict[int, list[float]] = defaultdict(list)
        for player in players:
            try:
                tier = int(player.get("tier") or 99)
            except (TypeError, ValueError):
                tier = 99
            tier_values[tier].append(player["_core"])
        ordered_tiers = sorted(tier_values)
        current_tier = ordered_tiers[0] if ordered_tiers else 99
        current_tier_scores = tier_values.get(current_tier, [])
        next_tier_scores = tier_values.get(ordered_tiers[1], []) if len(ordered_tiers) > 1 else []
        tier_remaining = len(current_tier_scores)
        tier_cliff = max(0.0, (mean(current_tier_scores) if current_tier_scores else 0) - (mean(next_tier_scores[:4]) if next_tier_scores else (depth_score - 8)))

        run_pressure = 100.0 * recent_counts.get(position, 0) / max(1, len(recent_window))
        strength_score = _clamp(50 + (supply_ratio - 1.0) * 30 + (depth_score - 70) * 0.55)
        urgency = _clamp(100 - strength_score + tier_cliff * 1.6 + run_pressure * 0.30)

        if supply_ratio >= 1.35 and depth_score >= 72:
            label = "Deep"
        elif supply_ratio >= 0.95:
            label = "Balanced"
        elif supply_ratio >= 0.65:
            label = "Thin"
        else:
            label = "Critical"

        strengths: list[str] = []
        weaknesses: list[str] = []
        if elite_remaining >= 3:
            strengths.append(f"{elite_remaining} elite options remain")
        if supply_ratio >= 1.2:
            strengths.append("starter-quality supply exceeds estimated demand")
        if depth_score >= 78:
            strengths.append("strong depth behind the top option")
        if tier_remaining <= 2:
            weaknesses.append(f"only {tier_remaining} player{'s' if tier_remaining != 1 else ''} remain in the top tier")
        if tier_cliff >= 8:
            weaknesses.append(f"{tier_cliff:.0f}-point quality cliff to the next tier")
        if run_pressure >= 30:
            weaknesses.append("position run is developing")
        if supply_ratio < 0.75:
            weaknesses.append("starter-quality supply is below estimated league demand")
        if not strengths:
            strengths.append("no major depth advantage")
        if not weaknesses:
            weaknesses.append("no immediate scarcity warning")

        result[position] = {
            "position": position,
            "strength": label,
            "strength_score": round(strength_score),
            "urgency_score": round(urgency),
            "starter_quality_remaining": starter_quality,
            "elite_remaining": elite_remaining,
            "estimated_demand_remaining": demand_remaining,
            "supply_ratio": round(supply_ratio, 2),
            "top_tier": current_tier if current_tier < 99 else None,
            "top_tier_remaining": tier_remaining,
            "tier_cliff": round(tier_cliff, 1),
            "run_pressure": round(run_pressure),
            "strengths": strengths,
            "weaknesses": weaknesses,
        }
    return result


def rank_candidates(
    available: list[dict[str, Any]],
    *,
    league: dict[str, Any],
    roster: list[dict[str, Any]] | None = None,
    recent_picks: list[dict[str, Any]] | None = None,
    overall_pick: int,
    next_overall: int | None,
    round_no: int,
    total_rounds: int = 15,
    strategy: str = "balanced",
) -> dict[str, Any]:
    roster = roster or []
    recent_picks = recent_picks or []
    overall_pick = max(1, int(overall_pick or 1))
    round_no = max(1, int(round_no or 1))
    total_rounds = max(round_no, int(total_rounds or 15))

    projection_pct = _percentile_scores(available, "projection")
    history_pct = _percentile_scores(available, "previous_points")
    groups = analyze_position_groups(available, league=league, recent_picks=recent_picks)
    weights = _stage_weights(round_no, total_rounds)
    roster_counts = _roster_counts(roster)
    starters = _league_starters(league)

    ranked: list[dict[str, Any]] = []
    for player in available:
        item = dict(player)
        name = str(item.get("name") or "")
        position = _pos(item.get("pos") or item.get("position"))
        item["pos"] = position

        scoring = _clamp(item.get("scoring_score") or item.get("scoring_potential") or projection_pct.get(name, 50))
        usage = _clamp(item.get("usage_score"), 55)
        quality = _candidate_core_score(item, projection_pct, history_pct)
        need = _roster_need_score(position, roster, league, round_no, total_rounds)
        league_fit = _league_fit_score(position, item, league)
        market, value_vs_adp = _market_grade(item.get("adp"), overall_pick)
        survival = survival_probability(item.get("adp"), next_overall)
        next_urgency = 100 - survival
        group = groups.get(position, {})
        group_urgency = _num(group.get("urgency_score"), 50)

        # If this exact player is one of the last members of a top tier, the
        # positional group is more urgent than its broad depth score suggests.
        try:
            player_tier = int(item.get("tier") or 99)
        except (TypeError, ValueError):
            player_tier = 99
        if player_tier == group.get("top_tier") and int(group.get("top_tier_remaining") or 99) <= 2:
            group_urgency = max(group_urgency, 88.0)

        components = {
            "scoring_potential": scoring,
            "player_quality": quality,
            "roster_need": need,
            "league_fit": league_fit,
            "group_urgency": _clamp(group_urgency),
            "usage_role": usage,
            "market_value": market,
            "next_pick_urgency": _clamp(next_urgency),
        }
        raw_score = sum(components[key] * weights[key] for key in weights)

        # Draft strategy is a light tie-breaker, never the main engine.  It can
        # shape two similarly graded choices without forcing a bad player.
        strategy_key = str(strategy or "balanced").lower().replace("_", "-")
        strategy_adjustment = 0.0
        if strategy_key == "zero-rb":
            if position == "WR" and round_no <= 5:
                strategy_adjustment = 4.0
            elif position == "RB" and round_no <= 4:
                strategy_adjustment = -4.0
        elif strategy_key == "hero-rb":
            if position == "RB" and round_no <= 2 and roster_counts.get("RB", 0) == 0:
                strategy_adjustment = 4.0
            elif position == "WR" and 2 <= round_no <= 7:
                strategy_adjustment = 2.0
        elif strategy_key == "robust-rb" and position == "RB" and round_no <= 4:
            strategy_adjustment = 3.0
        elif strategy_key == "late-qb" and position == "QB" and round_no <= 6:
            strategy_adjustment = -5.0
        raw_score += strategy_adjustment

        # Practical roster/draft safety rules.
        hard_cap = 99.0
        injury = str(item.get("injury_status") or "").upper()
        if item.get("active") is False:
            hard_cap = min(hard_cap, 10.0)
        if str(item.get("team") or "").upper() in {"", "FA"}:
            hard_cap = min(hard_cap, 25.0)
        if any(token in injury for token in ("IR", "PUP", "SUSP", "OUT")):
            hard_cap = min(hard_cap, 38.0)
        elif "DOUBTFUL" in injury:
            raw_score -= 12.0
        elif "QUESTIONABLE" in injury:
            raw_score -= 4.0

        if position in {"K", "DEF"}:
            direct_required = int(starters.get(position, 0))
            if direct_required <= 0:
                hard_cap = min(hard_cap, 20.0)
            elif round_no < max(8, total_rounds - 2):
                hard_cap = min(hard_cap, 18.0)

        # Prevent excess luxury picks at positions already well beyond the
        # league lineup/depth need unless the player is exceptional value.
        direct = int(starters.get(position, 0))
        depth_cap = direct + (3 if position in {"RB", "WR"} else 2)
        if direct and roster_counts.get(position, 0) >= depth_cap and market < 90:
            raw_score -= 10.0

        score = round(_clamp(raw_score, 0, hard_cap))

        if score >= 90:
            action = "DRAFT NOW"
        elif score >= 84:
            action = "STRONG PICK"
        elif score >= 77:
            action = "GOOD PICK"
        elif score >= 69:
            action = "CONSIDER"
        else:
            action = "WAIT / LOOK ELSEWHERE"
        if survival >= 72 and score < 88:
            action = "CAN LIKELY WAIT"
        elif survival <= 18 and score >= 78:
            action = "DRAFT NOW"

        reasons: list[str] = []
        if quality >= 86:
            reasons.append("elite player-quality grade")
        if scoring >= 86:
            reasons.append("top scoring potential among remaining positional peers")
        if need >= 86:
            reasons.append("fills an important roster need")
        if league_fit >= 86:
            reasons.append("league settings increase this position's value")
        if group_urgency >= 82:
            weaknesses = group.get("weaknesses") or []
            reasons.append(weaknesses[0] if weaknesses else "position group is thinning quickly")
        if usage >= 84:
            reasons.append(f"secure {item.get('role_label') or item.get('usage_role') or 'starter'} role/usage")
        elif usage < 58:
            reasons.append(f"usage concern: {item.get('role_label') or item.get('usage_role') or 'limited role'}")
        if value_vs_adp >= 6:
            reasons.append(f"{value_vs_adp:+.1f} picks of ADP value")
        elif value_vs_adp <= -10:
            reasons.append(f"{abs(value_vs_adp):.1f} picks ahead of ADP")
        if next_overall:
            reasons.append(f"{survival}% chance to survive to your next pick")
        if not reasons:
            reasons.append("balanced quality, scoring, role and roster fit")

        ranked.append({
            **item,
            "engine_version": ENGINE_VERSION,
            "draft_score": score,
            "recommendation": action,
            "components": {key: round(value) for key, value in components.items()},
            "weights": {key: round(value * 100, 1) for key, value in weights.items()},
            "adp_value": value_vs_adp,
            "survival_probability": survival,
            "position_group": group,
            "strategy_adjustment": round(strategy_adjustment, 1),
            "reasons": reasons,
            "rationale": f"{name} — {action}: " + "; ".join(reasons) + ".",
        })

    ranked.sort(
        key=lambda item: (
            item.get("draft_score", 0),
            item.get("components", {}).get("player_quality", 0),
            item.get("components", {}).get("scoring_potential", 0),
            -_num(item.get("adp"), 999),
        ),
        reverse=True,
    )

    return {
        "engine_version": ENGINE_VERSION,
        "weights": {key: round(value * 100, 1) for key, value in weights.items()},
        "position_groups": groups,
        "ranked": ranked,
        "recommended": ranked[0] if ranked else None,
        "alternatives": ranked[1:5],
    }

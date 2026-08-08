"""Build Gridiron IQ's bundled defensive and weekly-matchup snapshot.

All large public source files are reduced to one compact JSON artifact so the
Render app performs no network requests while a user sorts or opens matchups.
"""

import csv
import gzip
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


STATS_SEASON = int(os.getenv("GRIDIRON_STATS_SEASON", "2025"))
MATCHUP_SEASON = int(os.getenv("GRIDIRON_MATCHUP_SEASON", "2026"))
INPUT_DIR = Path(os.getenv("GRIDIRON_REFRESH_INPUT_DIR", "/tmp"))
PLAYER_STATS = Path(os.getenv("GRIDIRON_PLAYER_STATS_CSV", INPUT_DIR / f"stats_player_reg_{STATS_SEASON}.csv"))
PFR_DEFENSE = Path(os.getenv("GRIDIRON_PFR_DEFENSE_CSV", INPUT_DIR / "advstats_season_def.csv"))
SNAP_COUNTS = Path(os.getenv("GRIDIRON_SNAP_COUNTS_CSV", INPUT_DIR / f"snap_counts_{STATS_SEASON}.csv"))
PLAY_BY_PLAY = Path(os.getenv("GRIDIRON_PLAY_BY_PLAY_CSV", INPUT_DIR / f"play_by_play_{STATS_SEASON}.csv.gz"))
PARTICIPATION = Path(os.getenv("GRIDIRON_PARTICIPATION_CSV", INPUT_DIR / f"pbp_participation_{STATS_SEASON}.csv"))
FTN_CHARTING = Path(os.getenv("GRIDIRON_FTN_CHARTING_CSV", INPUT_DIR / f"ftn_charting_{STATS_SEASON}.csv"))
ROSTER_CURRENT = Path(os.getenv("GRIDIRON_ROSTER_CSV", INPUT_DIR / f"roster_{MATCHUP_SEASON}.csv"))
SCHEDULES = Path(os.getenv("GRIDIRON_SCHEDULES_CSV", INPUT_DIR / "games.csv"))
OFFENSE_SNAPSHOT = Path(os.getenv("GRIDIRON_OFFENSE_SNAPSHOT", f"data/nfl_player_stats_{STATS_SEASON}.json"))
OUTPUT = Path(os.getenv("GRIDIRON_DEFENSE_OUTPUT", "data/nfl_defensive_stats_current.json"))


def number(value, default=0.0):
    if value in (None, "", "NA", "NaN", "nan", "null", "--"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value):
    return int(round(number(value)))


def rounded(value, digits=1):
    if value is None:
        return None
    result = round(float(value), digits)
    return int(result) if digits == 0 else result


def divide(numerator, denominator, multiplier=1.0, digits=2):
    denominator = number(denominator)
    if denominator <= 0:
        return None
    return round(number(numerator) / denominator * multiplier, digits)


def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def team_code(value):
    value = str(value or "").upper().strip()
    return {
        "LAR": "LA", "STL": "LA", "JAC": "JAX", "OAK": "LV",
        "SD": "LAC", "SDG": "LAC", "WAS": "WAS", "WSH": "WAS",
    }.get(value, value)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def read_gzip_csv(path):
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def bool_number(value):
    return 1 if str(value or "").upper() in {"1", "TRUE", "T", "YES"} else 0


def role_for(position, depth=""):
    detail = str(depth or position or "").upper()
    if detail in {"CB", "NB"}:
        return "CB"
    if detail in {"S", "FS", "SS", "DB"}:
        return "S"
    if detail in {"DE", "EDGE", "OLB"}:
        return "EDGE"
    if detail in {"DT", "NT", "DL"}:
        return "DL"
    if detail in {"LB", "ILB", "MLB"}:
        return "LB"
    if position in {"DB", "CB", "S", "FS", "SS"}:
        return "DB"
    if position in {"DL", "DE", "DT", "NT"}:
        return "DL"
    if position in {"LB", "OLB", "ILB", "MLB"}:
        return "LB"
    return detail or "DEF"


def broad_group(role):
    if role in {"CB", "S", "DB"}:
        return "DB"
    if role in {"DL", "EDGE"}:
        return "DL"
    return "LB" if role == "LB" else "DEF"


def percentile_map(rows, field, higher_is_better=True):
    values = sorted(
        (number(row.get(field)), index)
        for index, row in enumerate(rows)
        if row.get(field) not in (None, "")
    )
    if not values:
        return {}
    result = {}
    total = max(1, len(values) - 1)
    for order, (_, index) in enumerate(values):
        pct = order / total * 98 + 1
        result[index] = pct if higher_is_better else 100 - pct
    return result


def assign_composite(rows, output_field, components):
    scores = [0.0 for _ in rows]
    weight_total = sum(weight for _, _, weight in components) or 1
    for field, higher_is_better, weight in components:
        grades = percentile_map(rows, field, higher_is_better)
        for index in range(len(rows)):
            scores[index] += grades.get(index, 50) * weight
    for index, row in enumerate(rows):
        row[output_field] = round(scores[index] / weight_total, 1)


# Current roster supplies matchup-season team assignments and detailed positions.
roster_by_gsis = {}
roster_by_pfr = {}
for row in read_csv(ROSTER_CURRENT):
    if row.get("season") != str(MATCHUP_SEASON) or row.get("game_type") != "REG":
        continue
    clean = {
        "name": row.get("full_name") or "",
        "team": team_code(row.get("team")),
        "position": str(row.get("position") or "").upper(),
        "depth_position": str(row.get("depth_chart_position") or "").upper(),
        "status": row.get("status") or "",
        "gsis_id": row.get("gsis_id") or "",
        "pfr_id": row.get("pfr_id") or "",
    }
    if clean["gsis_id"]:
        roster_by_gsis[clean["gsis_id"]] = clean
    if clean["pfr_id"]:
        roster_by_pfr[clean["pfr_id"]] = clean

current_players = {}
for roster_player in roster_by_gsis.values():
    player_name = str(roster_player.get("name") or "").strip()
    player_position = str(roster_player.get("position") or "").upper()
    if not player_name or player_position not in {"QB", "RB", "FB", "WR", "TE", "K"}:
        continue
    current_players[norm(player_name)] = {
        "full_name": player_name,
        "player_id": roster_player.get("gsis_id") or "",
        "team": roster_player.get("team") or "FA",
        "position": "RB" if player_position == "FB" else player_position,
        "status": roster_player.get("status") or "",
    }


offense_payload = json.loads(OFFENSE_SNAPSHOT.read_text(encoding="utf-8"))
offense_players = offense_payload.get("players", {})
offense_by_id = {
    str(record.get("player_id")): record
    for record in offense_players.values()
    if record.get("player_id")
}


# Base individual defensive stats.
players = {}
players_by_name = {}
for row in read_csv(PLAYER_STATS):
    if row.get("season_type") != "REG":
        continue
    defensive_total = sum(
        number(row.get(field))
        for field in (
            "def_tackles_solo", "def_tackles_with_assist", "def_tackle_assists",
            "def_tackles_for_loss", "def_fumbles_forced", "def_sacks",
            "def_qb_hits", "def_interceptions", "def_pass_defended",
        )
    )
    base_position = str(row.get("position") or row.get("position_group") or "").upper()
    if defensive_total <= 0 and base_position not in {
        "CB", "DB", "S", "FS", "SS", "LB", "ILB", "MLB", "OLB",
        "DL", "DE", "DT", "NT",
    }:
        continue
    name = str(row.get("player_display_name") or row.get("player_name") or "").strip()
    if not name:
        continue
    gsis_id = str(row.get("player_id") or "")
    current = roster_by_gsis.get(gsis_id, {})
    defensive_positions = {
        "CB", "DB", "S", "FS", "SS", "LB", "ILB", "MLB", "OLB",
        "DL", "DE", "DT", "NT",
    }
    current_position = str(current.get("position") or "").upper()
    current_depth = str(current.get("depth_position") or "").upper()
    if (
        base_position not in defensive_positions
        and current_position not in {"DB", "LB", "DL"}
        and current_depth not in defensive_positions
    ):
        continue
    detail_position = current.get("depth_position") or base_position
    role = role_for(current.get("position") or base_position, detail_position)
    if broad_group(role) == "DEF":
        continue
    key = gsis_id or norm(name)
    record = {
        "player_key": key,
        "name": current.get("name") or name,
        "player_id": gsis_id,
        "pfr_id": current.get("pfr_id") or "",
        "position": detail_position,
        "role": role,
        "position_group": broad_group(role),
        "stats_team": team_code(row.get("recent_team") or row.get("team")),
        "team_2025": team_code(row.get("recent_team") or row.get("team")),
        "team": current.get("team") or "FA",
        "roster_status": current.get("status") or "FA",
        "games": integer(row.get("games")),
        "solo_tackles": integer(row.get("def_tackles_solo")),
        "assisted_tackles": integer(row.get("def_tackle_assists")),
        "tackles_with_assist": integer(row.get("def_tackles_with_assist")),
        "total_tackles": integer(row.get("def_tackles_solo")) + integer(row.get("def_tackle_assists")) + integer(row.get("def_tackles_with_assist")),
        "tackles_for_loss": integer(row.get("def_tackles_for_loss")),
        "forced_fumbles": integer(row.get("def_fumbles_forced")),
        "sacks": rounded(number(row.get("def_sacks")), 1),
        "qb_hits": integer(row.get("def_qb_hits")),
        "interceptions": integer(row.get("def_interceptions")),
        "interception_yards": integer(row.get("def_interception_yards")),
        "passes_defended": integer(row.get("def_pass_defended")),
        "defensive_tds": integer(row.get("def_tds")),
        "safeties": integer(row.get("def_safeties")),
    }
    players[key] = record
    players_by_name[norm(name)] = record


def player_from_pfr(row):
    pfr_id = str(row.get("pfr_id") or row.get("pfr_player_id") or "")
    current = roster_by_pfr.get(pfr_id)
    if current and current.get("gsis_id") in players:
        return players[current["gsis_id"]]
    return players_by_name.get(norm(row.get("player") or row.get("pfr_player_name")))


# Defensive snap participation, weighted by implied team defensive snaps.
snap_totals = defaultdict(lambda: {"snaps": 0.0, "team_snaps": 0.0})
for row in read_csv(SNAP_COUNTS):
    if row.get("season") != str(STATS_SEASON) or row.get("game_type") != "REG":
        continue
    record = player_from_pfr(row)
    if not record:
        continue
    snaps = number(row.get("defense_snaps"))
    pct = number(row.get("defense_pct"))
    snap_totals[record["player_key"]]["snaps"] += snaps
    if snaps > 0 and pct > 0:
        snap_totals[record["player_key"]]["team_snaps"] += snaps / pct

for key, totals in snap_totals.items():
    record = players.get(key)
    if not record:
        continue
    record["defense_snaps"] = round(totals["snaps"])
    record["snap_share"] = divide(totals["snaps"], totals["team_snaps"], 100, 1)


# PFR coverage, pass rush and missed-tackle summaries.
for row in read_csv(PFR_DEFENSE):
    if row.get("season") != str(STATS_SEASON):
        continue
    record = player_from_pfr(row)
    if not record:
        continue
    record.update({
        "coverage_targets": integer(row.get("tgt")),
        "completions_allowed": integer(row.get("cmp")),
        "completion_rate_allowed": rounded(number(row.get("cmp_percent")) * 100, 1),
        "coverage_yards": integer(row.get("yds")),
        "yards_per_completion_allowed": rounded(number(row.get("yds_cmp")), 1),
        "yards_per_target_allowed": rounded(number(row.get("yds_tgt")), 1),
        "coverage_tds_allowed": integer(row.get("td")),
        "passer_rating_allowed": rounded(number(row.get("rat")), 1),
        "coverage_adot": rounded(number(row.get("dadot")), 1),
        "coverage_air_yards": integer(row.get("air")),
        "coverage_yac_allowed": integer(row.get("yac")),
        "blitzes": integer(row.get("bltz")),
        "hurries": integer(row.get("hrry")),
        "qb_knockdowns": integer(row.get("qbkd")),
        "pressures": integer(row.get("prss")),
        "missed_tackles": integer(row.get("m_tkl")),
        "missed_tackle_rate": rounded(number(row.get("m_tkl_percent")) * 100, 1),
        "batted_passes": integer(row.get("bats")),
    })


# Full play-by-play lookup used by the participation/coverage rows.
# Track the latest represented regular-season week so the UI can tell users
# exactly how current the weekly model is.
pbp = {}
data_through_week = 0
for row in read_gzip_csv(PLAY_BY_PLAY):
    if row.get("season_type") != "REG":
        continue
    data_through_week = max(data_through_week, integer(row.get("week")))
    pbp[(row.get("game_id"), str(row.get("play_id")))] = row


ftn = {}
for row in read_csv(FTN_CHARTING):
    if row.get("season") != str(STATS_SEASON):
        continue
    ftn[(row.get("nflverse_game_id"), str(row.get("nflverse_play_id")))] = row


def metric_bucket():
    return defaultdict(float)


team_defense = defaultdict(metric_bucket)
team_offense = defaultdict(metric_bucket)
coverage_counts = defaultdict(lambda: defaultdict(float))
coverage_results = defaultdict(lambda: defaultdict(metric_bucket))
allowed_position = defaultdict(lambda: defaultdict(metric_bucket))
receiver_splits = defaultdict(lambda: defaultdict(metric_bucket))
route_results = defaultdict(lambda: defaultdict(metric_bucket))
personnel_counts = defaultdict(metric_bucket)


for part in read_csv(PARTICIPATION):
    game_id = part.get("nflverse_game_id")
    play_id = str(part.get("play_id"))
    play = pbp.get((game_id, play_id))
    if not play:
        continue
    offense = team_code(play.get("posteam") or part.get("possession_team"))
    defense = team_code(play.get("defteam"))
    if not offense or not defense:
        continue
    defense_bucket = team_defense[defense]
    offense_bucket = team_offense[offense]
    is_pass = number(play.get("pass_attempt")) == 1
    is_rush = number(play.get("rush_attempt")) == 1
    is_dropback = number(play.get("qb_dropback")) == 1 or is_pass or number(play.get("sack")) == 1
    complete = number(play.get("complete_pass")) == 1
    yards = number(play.get("yards_gained"))
    epa = number(play.get("epa"))
    success = number(play.get("success"))
    pressure = bool_number(part.get("was_pressure"))
    rushers = number(part.get("number_of_pass_rushers"))
    box = number(part.get("defenders_in_box"))
    charted = ftn.get((game_id, play_id), {})
    blitz = 1 if number(charted.get("n_blitzers")) > 0 else 0

    # Personnel uses actual on-field position lists.
    defense_positions = [value for value in str(part.get("defense_positions") or "").split(";") if value]
    defensive_backs = sum(value.upper() in {"CB", "DB", "S", "FS", "SS"} for value in defense_positions)
    if defensive_backs:
        personnel_counts[defense]["plays"] += 1
        if defensive_backs <= 4:
            personnel_counts[defense]["base"] += 1
        elif defensive_backs == 5:
            personnel_counts[defense]["nickel"] += 1
        else:
            personnel_counts[defense]["dime"] += 1

    if is_dropback:
        for bucket in (defense_bucket, offense_bucket):
            bucket["dropbacks"] += 1
            bucket["pass_epa"] += epa
            bucket["pass_success"] += success
            bucket["pressures"] += pressure
            bucket["rush_five_plus"] += 1 if rushers >= 5 else 0
            bucket["blitzes"] += blitz
            bucket["sacks"] += number(play.get("sack"))
            bucket["qb_hits"] += number(play.get("qb_hit"))
        if is_pass:
            for bucket in (defense_bucket, offense_bucket):
                bucket["pass_attempts"] += 1
                bucket["completions"] += 1 if complete else 0
                bucket["pass_yards"] += yards if complete else 0
                bucket["pass_tds"] += number(play.get("pass_touchdown"))
                bucket["interceptions"] += number(play.get("interception"))
                bucket["explosive_passes"] += 1 if complete and yards >= 20 else 0
                bucket["air_yards"] += number(play.get("air_yards"))
                bucket["yac"] += number(play.get("yards_after_catch"))

    if is_rush:
        for bucket in (defense_bucket, offense_bucket):
            bucket["rush_attempts"] += 1
            bucket["rush_yards"] += yards
            bucket["rush_tds"] += number(play.get("rush_touchdown"))
            bucket["rush_epa"] += epa
            bucket["rush_success"] += success
            bucket["stuffs"] += 1 if yards <= 0 else 0
            bucket["explosive_runs"] += 1 if yards >= 10 else 0
            bucket["box_total"] += box
            bucket["box_plays"] += 1 if box > 0 else 0

    man_zone = str(part.get("defense_man_zone_type") or "").upper()
    coverage = str(part.get("defense_coverage_type") or "").upper()
    if is_dropback and man_zone:
        coverage_counts[defense][man_zone] += 1
    if is_dropback and coverage:
        coverage_counts[defense][coverage] += 1
    for label in (man_zone, coverage):
        if not label or not is_dropback:
            continue
        split = coverage_results[defense][label]
        split["dropbacks"] += 1
        split["attempts"] += 1 if is_pass else 0
        split["completions"] += 1 if complete else 0
        split["yards"] += yards if complete else 0
        split["tds"] += number(play.get("pass_touchdown"))
        split["interceptions"] += number(play.get("interception"))
        split["epa"] += epa
        split["success"] += success
        split["pressure"] += pressure

    receiver_id = str(play.get("receiver_player_id") or "")
    if is_pass and receiver_id:
        offense_record = offense_by_id.get(receiver_id, {})
        receiver_position = str(offense_record.get("position") or roster_by_gsis.get(receiver_id, {}).get("position") or "").upper()
        if receiver_position == "FB":
            receiver_position = "RB"
        if receiver_position in {"WR", "TE", "RB"}:
            points = (1 + yards / 10 if complete else 0) + number(play.get("pass_touchdown")) * 6
            allowed = allowed_position[defense][receiver_position]
            allowed["targets"] += 1
            allowed["receptions"] += 1 if complete else 0
            allowed["yards"] += yards if complete else 0
            allowed["tds"] += number(play.get("pass_touchdown"))
            allowed["ppr_points"] += points
            allowed["epa"] += epa
            for label in (man_zone, coverage):
                if not label:
                    continue
                split = receiver_splits[receiver_id][label]
                split["targets"] += 1
                split["receptions"] += 1 if complete else 0
                split["yards"] += yards if complete else 0
                split["tds"] += number(play.get("pass_touchdown"))
                split["ppr_points"] += points
                split["epa"] += epa
            route = str(part.get("route") or "").upper()
            if route:
                route_bucket = route_results[defense][route]
                route_bucket["targets"] += 1
                route_bucket["receptions"] += 1 if complete else 0
                route_bucket["yards"] += yards if complete else 0
                route_bucket["tds"] += number(play.get("pass_touchdown"))
                route_bucket["ppr_points"] += points
                route_bucket["epa"] += epa


def finish_split(bucket):
    return {
        "dropbacks": integer(bucket.get("dropbacks")),
        "targets": integer(bucket.get("targets") or bucket.get("attempts")),
        "receptions": integer(bucket.get("receptions") or bucket.get("completions")),
        "yards": integer(bucket.get("yards")),
        "tds": integer(bucket.get("tds")),
        "interceptions": integer(bucket.get("interceptions")),
        "ppr_points": rounded(bucket.get("ppr_points"), 1),
        "ppr_per_target": divide(bucket.get("ppr_points"), bucket.get("targets") or bucket.get("attempts"), digits=2),
        "yards_per_target": divide(bucket.get("yards"), bucket.get("targets") or bucket.get("attempts"), digits=2),
        "epa_per_play": divide(bucket.get("epa"), bucket.get("dropbacks") or bucket.get("targets") or bucket.get("attempts"), digits=3),
        "success_rate": divide(bucket.get("success"), bucket.get("dropbacks"), 100, 1),
        "pressure_rate": divide(bucket.get("pressure"), bucket.get("dropbacks"), 100, 1),
    }


def finish_team(team, raw, defense=True):
    pass_attempts = raw.get("pass_attempts")
    rush_attempts = raw.get("rush_attempts")
    dropbacks = raw.get("dropbacks")
    result = {
        "team": team,
        "dropbacks": integer(dropbacks),
        "pass_attempts": integer(pass_attempts),
        "completions": integer(raw.get("completions")),
        "pass_yards": integer(raw.get("pass_yards")),
        "pass_tds": integer(raw.get("pass_tds")),
        "interceptions": integer(raw.get("interceptions")),
        "sacks": integer(raw.get("sacks")),
        "qb_hits": integer(raw.get("qb_hits")),
        "completion_rate": divide(raw.get("completions"), pass_attempts, 100, 1),
        "yards_per_attempt": divide(raw.get("pass_yards"), pass_attempts, digits=2),
        "pass_td_rate": divide(raw.get("pass_tds"), pass_attempts, 100, 1),
        "interception_rate": divide(raw.get("interceptions"), pass_attempts, 100, 1),
        "sack_rate": divide(raw.get("sacks"), dropbacks, 100, 1),
        "pressure_rate": divide(raw.get("pressures"), dropbacks, 100, 1),
        "rush_five_plus_rate": divide(raw.get("rush_five_plus"), dropbacks, 100, 1),
        "blitz_rate": divide(raw.get("blitzes"), dropbacks, 100, 1),
        "pass_epa_per_dropback": divide(raw.get("pass_epa"), dropbacks, digits=3),
        "pass_success_rate": divide(raw.get("pass_success"), dropbacks, 100, 1),
        "explosive_pass_rate": divide(raw.get("explosive_passes"), pass_attempts, 100, 1),
        "rush_attempts": integer(rush_attempts),
        "rush_yards": integer(raw.get("rush_yards")),
        "rush_tds": integer(raw.get("rush_tds")),
        "yards_per_carry": divide(raw.get("rush_yards"), rush_attempts, digits=2),
        "rush_epa_per_carry": divide(raw.get("rush_epa"), rush_attempts, digits=3),
        "rush_success_rate": divide(raw.get("rush_success"), rush_attempts, 100, 1),
        "stuff_rate": divide(raw.get("stuffs"), rush_attempts, 100, 1),
        "explosive_run_rate": divide(raw.get("explosive_runs"), rush_attempts, 100, 1),
        "average_box": divide(raw.get("box_total"), raw.get("box_plays"), digits=2),
    }
    if defense:
        cover_total = coverage_counts[team].get("MAN_COVERAGE", 0) + coverage_counts[team].get("ZONE_COVERAGE", 0)
        result["man_rate"] = divide(coverage_counts[team].get("MAN_COVERAGE"), cover_total, 100, 1)
        result["zone_rate"] = divide(coverage_counts[team].get("ZONE_COVERAGE"), cover_total, 100, 1)
        coverage_family_total = sum(coverage_counts[team].get(label, 0) for label in ("COVER_0", "COVER_1", "COVER_2", "COVER_3", "COVER_4", "COVER_6", "COVER_9", "2_MAN", "COMBO"))
        for label in ("COVER_0", "COVER_1", "COVER_2", "COVER_3", "COVER_4", "COVER_6", "COVER_9", "2_MAN", "COMBO"):
            result[label.lower() + "_rate"] = divide(coverage_counts[team].get(label), coverage_family_total, 100, 1)
        families = [(label, coverage_counts[team].get(label, 0)) for label in ("COVER_0", "COVER_1", "COVER_2", "COVER_3", "COVER_4", "COVER_6", "COVER_9", "2_MAN", "COMBO")]
        result["top_coverage"] = max(families, key=lambda item: item[1])[0] if families else ""
        personnel = personnel_counts[team]
        result["base_rate"] = divide(personnel.get("base"), personnel.get("plays"), 100, 1)
        result["nickel_rate"] = divide(personnel.get("nickel"), personnel.get("plays"), 100, 1)
        result["dime_rate"] = divide(personnel.get("dime"), personnel.get("plays"), 100, 1)
        result["coverage_splits"] = {
            label: finish_split(values)
            for label, values in coverage_results[team].items()
        }
        result["allowed_by_position"] = {
            position: finish_split(values)
            for position, values in allowed_position[team].items()
        }
        result["route_results"] = {
            route: finish_split(values)
            for route, values in sorted(route_results[team].items(), key=lambda item: -item[1].get("targets", 0))
            if values.get("targets", 0) >= 4
        }
    return result


teams = sorted(set(team_defense) | set(team_offense))
team_rows = [finish_team(team, team_defense[team], True) for team in teams]
offense_rows = [finish_team(team, team_offense[team], False) for team in teams]


# Team unit grades are percentile composites. Higher always means better.
assign_composite(team_rows, "secondary_grade", (
    ("pass_epa_per_dropback", False, 3), ("yards_per_attempt", False, 2),
    ("pass_td_rate", False, 1), ("interception_rate", True, 1),
    ("explosive_pass_rate", False, 1),
))
assign_composite(team_rows, "pass_rush_grade", (
    ("pressure_rate", True, 3), ("sack_rate", True, 2), ("qb_hits", True, 1),
))
assign_composite(team_rows, "run_defense_grade", (
    ("rush_epa_per_carry", False, 3), ("yards_per_carry", False, 2),
    ("stuff_rate", True, 2), ("explosive_run_rate", False, 1),
))
for row in team_rows:
    row["front_grade"] = round(row["pass_rush_grade"] * 0.55 + row["run_defense_grade"] * 0.45, 1)
    row["overall_grade"] = round(row["secondary_grade"] * 0.52 + row["front_grade"] * 0.48, 1)

assign_composite(offense_rows, "pass_protection_grade", (
    ("pressure_rate", False, 3), ("sack_rate", False, 2), ("pass_epa_per_dropback", True, 1),
))
assign_composite(offense_rows, "run_blocking_grade", (
    ("rush_epa_per_carry", True, 3), ("yards_per_carry", True, 2),
    ("stuff_rate", False, 2), ("explosive_run_rate", True, 1),
))
for row in offense_rows:
    row["offensive_line_grade"] = round(row["pass_protection_grade"] * 0.55 + row["run_blocking_grade"] * 0.45, 1)

for field in ("overall_grade", "secondary_grade", "front_grade", "pass_rush_grade", "run_defense_grade"):
    for rank, row in enumerate(sorted(team_rows, key=lambda item: -item[field]), 1):
        row[field.replace("grade", "rank")] = rank
for field in ("offensive_line_grade", "pass_protection_grade", "run_blocking_grade"):
    for rank, row in enumerate(sorted(offense_rows, key=lambda item: -item[field]), 1):
        row[field.replace("grade", "rank")] = rank


# Individual Gridiron IQ grades, normalized within broad position groups.
player_rows = [row for row in players.values() if row.get("games", 0) > 0]
for group in ("DB", "LB", "DL"):
    group_rows = [row for row in player_rows if row.get("position_group") == group]
    assign_composite(group_rows, "coverage_grade", (
        ("passer_rating_allowed", False, 3), ("yards_per_target_allowed", False, 2),
        ("completion_rate_allowed", False, 1), ("interceptions", True, 1),
        ("passes_defended", True, 1),
    ))
    assign_composite(group_rows, "pass_rush_grade", (
        ("pressures", True, 3), ("sacks", True, 2), ("qb_hits", True, 1),
        ("tackles_for_loss", True, 1),
    ))
    assign_composite(group_rows, "tackle_grade", (
        ("total_tackles", True, 2), ("tackles_for_loss", True, 1),
        ("missed_tackle_rate", False, 2),
    ))
    for row in group_rows:
        if group == "DB":
            row["defense_grade"] = round(row["coverage_grade"] * 0.72 + row["tackle_grade"] * 0.2 + row["pass_rush_grade"] * 0.08, 1)
        elif group == "DL":
            row["defense_grade"] = round(row["pass_rush_grade"] * 0.68 + row["tackle_grade"] * 0.27 + row["coverage_grade"] * 0.05, 1)
        else:
            row["defense_grade"] = round(row["coverage_grade"] * 0.35 + row["pass_rush_grade"] * 0.3 + row["tackle_grade"] * 0.35, 1)
    for rank, row in enumerate(sorted(group_rows, key=lambda item: -item["defense_grade"]), 1):
        row["position_rank"] = rank
        row["rank_label"] = f"{row['role']}{rank}"

for role in ("CB", "S", "LB", "DL", "EDGE"):
    role_rows = [row for row in player_rows if row.get("role") == role]
    for rank, row in enumerate(sorted(role_rows, key=lambda item: -item["defense_grade"]), 1):
        row["position_rank"] = rank
        row["rank_label"] = f"{role}{rank}"


# Coverage splits by offensive receiver, keyed by the app's normalized name.
receiver_split_output = {}
league_splits = defaultdict(lambda: defaultdict(metric_bucket))
for receiver_id, splits in receiver_splits.items():
    offense_record = offense_by_id.get(receiver_id)
    if not offense_record:
        continue
    name_key = norm(offense_record.get("name"))
    position = offense_record.get("position")
    receiver_split_output[name_key] = {
        "name": offense_record.get("name"),
        "player_id": receiver_id,
        "position": position,
        "splits": {label: finish_split(values) for label, values in splits.items()},
    }
    for label, values in splits.items():
        target = league_splits[position][label]
        for field, value in values.items():
            target[field] += value

league_split_output = {
    position: {label: finish_split(values) for label, values in splits.items()}
    for position, splits in league_splits.items()
}


# Current defender lists power the "likely primary matchup" selection.
current_defenders = defaultdict(list)
for row in player_rows:
    current_team = row.get("team")
    if current_team and current_team != "FA":
        current_defenders[current_team].append(row["player_key"])

for current_team, keys in current_defenders.items():
    keys.sort(key=lambda key: (
        -number(players[key].get("snap_share")),
        -number(players[key].get("coverage_targets")),
        -number(players[key].get("defense_grade")),
    ))


schedule = []
for row in read_csv(SCHEDULES):
    if row.get("season") != str(MATCHUP_SEASON) or row.get("game_type") != "REG":
        continue
    schedule.append({
        "week": integer(row.get("week")),
        "gameday": row.get("gameday") or "",
        "gametime": row.get("gametime") or "",
        "away_team": team_code(row.get("away_team")),
        "home_team": team_code(row.get("home_team")),
        "spread_line": rounded(number(row.get("spread_line")), 1),
        "total_line": rounded(number(row.get("total_line")), 1),
        "roof": row.get("roof") or "",
        "surface": row.get("surface") or "",
    })


payload = {
    "season": STATS_SEASON,
    "matchup_season": MATCHUP_SEASON,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "data_through_week": data_through_week,
    "source": f"{STATS_SEASON} nflverse player stats, PFR advanced defense, FTN Data participation via nflverse, and nflverse schedules",
    "license_note": "Participation and coverage data: FTN Data via nflverse, CC BY-SA 4.0.",
    "players": {row["player_key"]: row for row in player_rows},
    "teams": {row["team"]: row for row in team_rows},
    "offensive_lines": {row["team"]: row for row in offense_rows},
    "current_players": current_players,
    "current_defenders": dict(current_defenders),
    "receiver_splits": receiver_split_output,
    "league_receiver_splits": league_split_output,
    "schedule_2026": schedule,
}

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(json.dumps({
    "output": str(OUTPUT),
    "players": len(payload["players"]),
    "teams": len(payload["teams"]),
    "receiver_splits": len(payload["receiver_splits"]),
    "current_players": len(payload["current_players"]),
    "schedule_games": len(schedule),
}))

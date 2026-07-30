
from __future__ import annotations

import argparse
import json

from player_research_db import (
    build_everything,
    import_public_adp,
    import_adp,
    import_all_history,
    import_current_players,
    import_projections,
    import_season,
    repair_exact_player_duplicates,
    repair_recent_player_aliases,
    init_database,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Gridiron IQ SQLite Player Research database."
    )
    parser.add_argument("--all", action="store_true", help="Build history, then apply current teams, projections, and saved ADP.")
    parser.add_argument("--history", action="store_true", help="Import historical seasons.")
    parser.add_argument(
        "--career-history",
        action="store_true",
        help="Import every available completed NFL season from 1999 through 2025.",
    )
    parser.add_argument("--season", type=int, help="Import one NFL season.")
    parser.add_argument("--start", type=int, default=1999)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--players", action="store_true")
    parser.add_argument(
        "--repair-identities",
        action="store_true",
        help="Merge punctuation, spacing, capitalization, and safe suffix variants.",
    )
    parser.add_argument("--projections", action="store_true")
    parser.add_argument("--adp", choices=["ESPN", "YAHOO", "BOTH"])
    parser.add_argument("--public-adp", choices=["ESPN", "YAHOO", "BOTH"])
    args = parser.parse_args()

    init_database()
    result = {}

    if args.all:
        result = build_everything(args.start, args.end)
    else:
        if args.players:
            result["current_players"] = import_current_players()
        if args.repair_identities:
            result["exact_duplicate_repair"] = repair_exact_player_duplicates()
            result["identity_repair"] = repair_recent_player_aliases()
        if args.history:
            result["history"] = import_all_history(args.start, args.end)
        if args.career_history:
            result["career_history"] = import_all_history(1999, 2025)
            result["exact_duplicate_repair"] = repair_exact_player_duplicates()
            result["identity_repair"] = repair_recent_player_aliases()
            from player_research_db import database_status
            result["database_status"] = database_status()
        if args.season:
            result[f"season_{args.season}"] = import_season(args.season)
        if args.projections:
            result["projections"] = import_projections()
        if args.adp in {"ESPN", "BOTH"}:
            result["espn_adp"] = import_adp("ESPN")
        if args.adp in {"YAHOO", "BOTH"}:
            result["yahoo_adp"] = import_adp("YAHOO")
        if args.public_adp in {"ESPN", "BOTH"}:
            result["public_espn_adp"] = import_public_adp("ESPN")
        if args.public_adp in {"YAHOO", "BOTH"}:
            result["public_yahoo_adp"] = import_public_adp("YAHOO")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

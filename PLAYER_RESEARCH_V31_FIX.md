# Player Research v31 – hard stats join + cache fix

This update fixes the case where the Player Research page lists current players
but shows blank 2025 games/PPR even though `data/nfl_player_stats_2025.json`
already contains the season totals.

## Changes

- Forces a final authoritative 2025-stat join immediately before the table API
  response is built.
- Matches the saved stats using direct keys plus suffix-safe canonical identity.
- Restores actual 2025 games/PPR and full stat fields for individual profiles.
- Does not treat a legitimate zero fantasy-point game as "missing data".
- Stops stale browser/CDN copies of Player Research from surviving a deploy.
- Adds a visible **Player Data v31** badge to verify that the new code is live.
- Adds `build_id: v31` and sample-player checks to the Player Research diagnostic
  endpoint.

## Included 2025 data validation

The bundled snapshot contains 657 player-season records. Verified examples:
Jordan Mason, Aaron Jones, Saquon Barkley, Tank Bigsby and James Cook all have
2025 games and PPR totals in the included database.

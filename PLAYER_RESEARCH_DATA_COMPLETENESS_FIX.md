# Player Research Data Completeness Fix

## Problem corrected

Roster, statistics and ADP sources sometimes publish the same player with
different suffixes. For example, one source may use `Brian Robinson`, while
another uses `Brian Robinson Jr.`. The older merge treated those as two people,
leaving one row with team/depth data and another with ADP/statistics.

## Improvements

- Consolidates Jr., Sr., II, III, IV and V name variants into one current player
- Preserves the complete display name while merging team, depth, SOS, ADP and stats
- Removes duplicate suffix rows from Player Research
- Extends individual profile lookup from 1,000 to all 5,000 supported records
- Filters parent/child career-history collisions using player ID and experience
- Shows `N/A` for genuine free-agent depth/SOS fields
- Shows each veteran's latest available NFL stat season when they did not play
  in 2025, with a separate `Stat Yr` column so older totals are never mislabeled
- Calculates kicker fantasy totals from imported field-goal distance and PAT
  results when the source omits a fantasy-point total
- Consolidates the two names used for every defense (for example, `Broncos
  D/ST` and `Denver Broncos`) into one DEF row with team defensive totals
- Keeps genuine rookies and players with no regular-season appearance marked
  with a dash instead of manufacturing statistics

Verified examples include Brian Robinson Jr., Tyrone Tracy Jr., Chris
Rodriguez Jr., James Cook III, Tank Dell, Tyler Bass, Nick Chubb and the Denver
Broncos defense.

Upload the complete package contents to the existing GitHub repository and
redeploy Render. No new folder or environment variable is required.

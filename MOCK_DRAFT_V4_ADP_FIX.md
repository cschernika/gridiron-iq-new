# Gridiron IQ Mock Draft V4 — ADP and Player-Pool Repair

## What the screenshot revealed

The deployed app had accepted a partial current-player cache containing 297
quarterbacks. That caused every position tab except QB to show zero players.
The values in the ADP column were then generated fallback ranks, not verified
ESPN or Yahoo ADP.

V4 fixes both failures. A partial cache cannot replace the complete player
database, and a consensus rank is never labeled as platform ADP.

## Data protections

- The current-player directory must include at least 40 QB, 100 RB, 150 WR,
  80 TE, 10 K and 20 D/ST records.
- An incomplete persistent Render cache is ignored in favor of the complete
  player database shipped with the app.
- The 2026 master file and 2025 statistical snapshot are compared with their
  bundled copies; the most complete valid source wins.
- The daily refresh refuses to overwrite good data when an upstream response
  is incomplete or missing a position.
- A mock cannot start unless the final board contains at least 500 players and
  complete QB, RB, WR, TE, K and D/ST coverage.
- Previously saved mocks with partial boards are rebuilt automatically.

## Ranking and ADP rules

- Verified ESPN/Yahoo ADP is used only when the saved dataset has at least 75
  ranked players and meaningful QB, RB, WR and TE coverage.
- If verified platform ADP is unavailable, the table heading changes to
  `Consensus Rank` and every value is labeled `Gridiron IQ consensus`.
- A partial or single-position ADP response is rejected instead of being
  displayed as genuine platform ADP.
- ESPN league sync can capture ESPN's native PPR ADP. The existing Player
  Research ADP refresh remains the public-source fallback.

## Draft-selection formula

Computer teams use a market-first redraft formula:

| Input | Effect |
| --- | --- |
| Verified platform ADP or current consensus rank | Strongest signal; large reaches receive a steep penalty. |
| 2026 projection | Position-normalized value so raw QB totals do not dominate RB/WR value. |
| 2025 production | Small proven-production bonus; rookies are not penalized. |
| Roster needs and limits | Required starters, useful depth and hard position caps. |
| Draft personality | Mild RB-heavy, WR-heavy, Zero-RB, Hero-RB, QB timing or best-player preference. |
| Scoring format | Small Full-PPR, Half-PPR or Standard adjustment. |
| Tier cliffs and position runs | Tie-breakers within a realistic market window. |
| Injury, depth and team status | Penalizes serious injuries, buried depth and unsigned free agents. |

Kicker and D/ST remain unavailable until the final three rounds. The candidate
window is 18 picks in rounds 1–3, 26 picks in rounds 4–8 and 40 picks later.

## Deployment verification

The page checks `/api/diagnostics/mock-draft` before enabling Start. A correct
deployment shows a green message containing:

`Player database verified: 702 players`

and the page marker:

`DATA-SAFE PLAYER POOL V4 · SMART DRAFT FORMULA V4`

If the template was deployed without the matching `app.py`, the page displays
an old-server warning and keeps the draft disabled rather than producing an
incorrect simulation.

## Validation completed

- Corrupted persistent-cache fixture: 297 QB and zero other positions.
- Corrupted single-position ADP fixture: 297 QB-only rankings.
- Fallback result: 702 players — 100 QB, 180 RB, 260 WR, 100 TE, 30 K and
  32 D/ST.
- Twelve complete 12-team, 12-round drafts covering every user draft slot.
- 1,728 total selections with no duplicate players.
- Required positions and position caps verified for every team.
- No kicker or D/ST selected before round 10.
- No unsigned free-agent selection in the validation drafts.

Server build: `mock-draft-v4-cache-guard`  
Formula version: `smart-draft-v4`  
Player-pool version: `complete-v4`

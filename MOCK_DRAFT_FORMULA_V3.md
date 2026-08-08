# Gridiron IQ Smart Draft Formula V3

The mock-draft computer teams use a market-first redraft formula. A strategy
can break a close decision, but it cannot move a deep player hundreds of spots
ahead of current market value.

## Player eligibility

- Merges current roster data, saved ESPN/Yahoo ADP, the 2026 player master,
  2025 production and the Gridiron IQ preseason baseline.
- Treats suffix variants such as `Kenneth Walker` and `Kenneth Walker III` as
  one player.
- Removes explicitly inactive players and stale veteran free-agent records
  that have no current production or trusted platform ADP.
- Uses current team, injury, depth-chart and rookie information from the daily
  player refresh.

## Pick calculation

| Input | Formula effect |
| --- | --- |
| Current market rank / platform ADP | Strongest input. A reach loses 1.45 points per pick; a player falling past market gains 0.65 per pick, capped at 22. |
| 2026 projection | Position-normalized value from -2 to +10, so QB totals do not automatically outrank RB/WR value. |
| 2025 production | Proven-production bonus from 0 to +5. Rookies are not penalized for having no prior NFL season. |
| Roster construction | Starter need is +10; useful depth is +4; excess positions receive a growing penalty. |
| Draft strategy | Mild adjustment for balanced, RB-heavy, WR-heavy, Hero-RB, Zero-RB, early-QB, late-QB or best-player builds. |
| Scoring format | Small Full-PPR, Half-PPR or Standard adjustment by position. |
| Tier cliff | +2 or +4 when the next player at the position has a meaningful market-rank drop. |
| Position run | Up to +2.5 after several recent picks at the same position. |
| Team stack | Up to +1.5 for a sensible QB/WR or QB/TE stack in later decisions. |
| Injury / availability | Questionable -2, doubtful -8, IR/PUP/suspended/out -14, unsigned free agent -12. |
| Controlled variation | Only ±2.25, enough to vary repeated mocks without overruling an ADP tier. |

## Roster rules

- Every computer team must finish with the required QB, RB, WR and TE starters.
- Drafts of eight or more rounds also require one kicker and one defense.
- Kicker and defense are held until the final three rounds.
- Position caps prevent three- or four-quarterback teams and excessive tight
  end hoarding in a normal one-QB redraft league.
- If remaining picks equal the number of open required slots, the formula
  automatically forces those positions.

## Candidate window

Computer teams consider players within a realistic market window:

- Rounds 1-3: up to 18 picks beyond the current selection.
- Rounds 4-8: up to 26 picks beyond the current selection.
- Rounds 9-15: up to 40 picks beyond the current selection.

This prevents one noisy statistic from turning a late sleeper into an
unrealistic first-round pick.

## Validation completed

- ESPN Full PPR and Yahoo Half PPR.
- 10-, 12- and 15-round snake drafts.
- Multiple random seeds and every draft position.
- No duplicate players.
- Required roster positions and position caps verified for all teams.
- No early kicker or defense selections.
- Local API timing: approximately 0.12 seconds to start, 0.01 seconds to load
  state and 0.08 seconds to process a user pick plus intervening AI picks.

Formula version: `smart-draft-v3`  
Player-pool version: `complete-v3`

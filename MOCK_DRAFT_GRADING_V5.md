# Gridiron IQ Strict Draft Grading V5

## Corrected ADP direction

The previous calculation used `ADP - pick number` and treated a positive result
as value. That direction was backward. Selecting an ADP 724 player at pick 4
was incorrectly interpreted as excellent value instead of a 720-pick reach.

V5 uses:

`draft value = actual pick number - ADP`

- Positive: the player fell past ADP and was selected at a value.
- Negative: the player was selected earlier than ADP and was a reach.

The correction applies to Mock Draft Pick Score, Live Grade, completed draft
reports and Draft Center ADP value.

## Individual Pick Score

Each available player receives a 0–99 Pick Score for the current selection:

| Component | Weight | Purpose |
| --- | ---: | --- |
| Market grade | 74% | Compares the current pick directly with verified platform ADP or current consensus rank. Reach penalties accelerate after 8 and 20 picks. |
| Position-relative projection | 16% | Rewards production without allowing raw QB totals to dominate other positions. |
| Roster fit | 10% | Rewards unfilled needs and penalizes duplicate/excess positions. |

Hard limits apply to choices that should never receive a strong score:

- Kicker or D/ST before the final three rounds: maximum 12.
- Unsigned free agent: maximum 18.
- Explicitly inactive player: maximum 8.
- IR, PUP, suspended or out: maximum 35.

Kicker and D/ST selections in the final three rounds are not treated as huge
reaches merely because those positions appear near the bottom of overall ADP.

## Overall Live Grade

The previous category floors of 40–45 were removed. The Live Grade is now:

- 68% selection quality while the draft is in progress; 62% when complete.
- 17% roster construction while drafting; 22% when complete.
- 8–9% position-relative projected production.
- 7% prior production, with neutral treatment for rookies/no history.

Early selections receive slightly more weight. The grade also receives an
additional penalty for a very low worst pick and for each reach of 24 or more
picks.

The page displays selection quality, the worst pick and the number of severe
reaches under the Live Grade.

## Saved drafts

Previously saved V4 mocks are automatically recalculated with Strict V5 when
the Mock Draft page, draft state or completed review is opened. An old inflated
score is not preserved.

## Validation

| Scenario | Pick Score | Live/Final Grade |
| --- | ---: | ---: |
| Christian McCaffrey at pick 4, ADP 5 | 89 | 92 after the first pick |
| ADP 724 skill player at pick 4 | 20 | 35 after the first pick |
| Kicker in Round 1 | 1 | 9 after the first pick |
| Strong completed 12-round draft | — | 81 |
| Intentionally terrible but legal completed draft | — | 21 |

The strong-versus-terrible completed-draft separation is 60 grade points.

Server build: `mock-draft-v5-grade-calibration`  
Formula version: `smart-draft-v5`  
Grade version: `strict-v5`

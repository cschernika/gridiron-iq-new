# Gridiron IQ — Draft Center Pro

This upgrade turns Draft Center into a live draft war room.

## Features
- ESPN / Yahoo league selector
- Full-PPR vs Half-PPR league-aware player adjustments
- Best Pick Right Now recommendation
- Gridiron IQ score
- ADP value
- Roster fit
- Positional scarcity
- Tier-risk alerting
- Snake-draft upcoming-pick calculation
- Draft slot / current round / pick controls
- Strategy profiles:
  - Balanced
  - Best Value
  - Zero RB
  - Hero RB
  - Robust RB
  - Late QB
- Roster construction panel
- Position-need meter
- Live available-player board
- Drafted-player tracking
- Draft log
- Draft simulator foundation

## Installation

### 1. Replace
`templates/draft_center.html`

### 2. Append
Append all of `static/draft_center_pro.css` to the bottom of your current `static/app.css`.

### 3. Append
Append all of `static/draft_center_pro.js` to the bottom of your current `static/app.js`.

### 4. Update app.py
Use `patches/app_draft_center_pro_patch.py`.

Important:
- Add its imports/constants/helpers.
- REPLACE the existing `/draft-center` route with the new route.
- Add the `/api/draft/pro/...` endpoints.
- Do not leave two functions/routes named `draft_center`, or Flask will fail with a duplicate endpoint error.

## Current ESPN/Yahoo behavior
The architecture is platform-neutral. The included contexts are:

- Gramp's Gridiron — ESPN — Full PPR
- WestRockers — Yahoo — Half PPR

The next integration step is to populate these contexts directly from persisted ESPN and Yahoo league records instead of the included defaults.

## Important draft-tracking note
For this development build, clicking `Available` marks that player as drafted by YOUR team so the roster-construction logic is easy to test.

The next version should add:
- "Drafted by" team selector
- automatic live draft event ingestion
- only add the player to your roster when your team made the pick

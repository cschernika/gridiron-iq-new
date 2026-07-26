# Gridiron IQ — Command Center Redesign

This patch fixes the Command Center shown in the screenshot.

## Fixes
- Removes the giant raw ESPN scoring-rules dump from the Teams card.
- Shows a short scoring label instead.
- Replaces misleading pre-draft Team Strength / Rank data with Draft Status.
- Adds pre-draft priorities.
- Adds your connected league teams.
- Highlights Chad's Team.
- Makes the dashboard useful before the 2026 draft.
- Leaves room for the dashboard to transition to weekly team analytics after rosters populate.

## Files
1. Replace `templates/dashboard.html`
2. Add the CSS in `static/app_command_center.css` to the bottom of your existing `static/app.css`
3. Update the `scoring_label()` and `build_settings()` helpers in `app.py` using `app_settings_patch.py`

Do not replace the rest of `app.py` if ESPN sync is already working.

# James Cook Team and Depth-Chart Fix

James Cook is represented as:

- NFL team: `BUF`
- Position: `RB`
- Buffalo depth chart: `RB1`
- Jersey number: `4`

The app now reconciles the persistent Render player cache with the bundled
daily roster snapshot. A stale `FA` or blank value can no longer overwrite a
confirmed NFL team or published depth-chart slot.

The correction applies to:

- Player Research table
- Individual player profile
- Draft Center recommendations
- Mock Draft player pool
- Existing saved mock drafts (the player pool upgrades to `complete-v5`)

Upload the complete package to the root of the GitHub repository, commit the
files, and redeploy Render. No new environment variable is required.

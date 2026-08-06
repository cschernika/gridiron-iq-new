# Gridiron IQ weekly statistics updates

The included GitHub Actions workflow refreshes the current-season offensive
and defensive snapshots every Tuesday morning. When it commits new data to the
`main` branch, Render's normal **Auto-Deploy: On Commit** setting publishes the
update automatically.

## One-time setup

1. Upload the `.github/workflows/weekly-nfl-stats.yml`,
   `refresh_weekly_data.py`, and `build_defensive_snapshot.py` files from this
   package to the matching locations in your GitHub project.
2. In GitHub, open **Settings → Actions → General → Workflow permissions**.
3. Select **Read and write permissions**, then save.
4. In Render, open the Gridiron IQ web service, select **Settings**, and confirm
   **Auto-Deploy** is set to **On Commit**.
5. To test immediately, open the GitHub **Actions** tab, choose
   **Weekly NFL statistics refresh**, select **Run workflow**, and run it on
   `main`.

The updater is intentionally safe before the regular season begins: if 2026
regular-season files have not been published, it keeps the existing 2025
baseline and exits without replacing it. Once current data is available, the
Offensive Statistics page switches to 2026 actual totals and the Defensive
Statistics and Weekly Matchup pages use the refreshed 2026 baseline.

## Files updated automatically

- `data/nfl_player_stats_2026.json`
- `data/nfl_defensive_stats_current.json`

No FantasyPros key or paid data subscription is required for this refresh.

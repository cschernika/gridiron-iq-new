# Gridiron IQ automatic data updates

The package includes two GitHub Actions workflows:

- **Daily Player Research refresh** runs every day at **6:37 AM Eastern**. It
  refreshes player teams, new signings, free agents, active status, injuries,
  practice status and depth-chart fields from Sleeper's current NFL directory.
- **Weekly NFL statistics refresh** runs every Tuesday morning. It refreshes
  current-season offensive and defensive production.

Each workflow commits its refreshed data to `main`. Render's normal
**Auto-Deploy: On Commit** setting then publishes the update automatically.

## One-time setup

1. Upload these files from the package to the matching locations in your
   GitHub project:

   - `.github/workflows/daily-player-research.yml`
   - `.github/workflows/weekly-nfl-stats.yml`
   - `refresh_daily_player_research.py`
   - `refresh_weekly_data.py`
   - `build_defensive_snapshot.py`

   Do not create another project folder. The `.github` folder belongs at the
   top level of the same repository as `app.py`.
2. In GitHub, open **Settings → Actions → General → Workflow permissions**.
3. Select **Read and write permissions**, then save.
4. In Render, open the Gridiron IQ web service, select **Settings**, and confirm
   **Auto-Deploy** is set to **On Commit**.
5. To update Player Research immediately, open the GitHub **Actions** tab,
   choose **Daily Player Research refresh**, select **Run workflow**, and run
   it on `main`. This is the quickest way to import a newly published signing
   instead of waiting until the next morning.
6. You can test weekly statistics the same way by choosing
   **Weekly NFL statistics refresh**.

## What updates daily

- Current NFL team and free-agent status
- Newly listed players and signings
- Active/inactive status
- Injury and practice status
- Depth-chart position and order
- Recent player news and detected team changes for the update badge

Player Research preserves existing projections, ADP and historical statistics
when those current-player fields change. A transaction appears after Sleeper
publishes it in its player directory and the next daily workflow runs.

On the Player Research table, a red **✚** badge means the player has an active
injury designation. A blue **news** badge means a player story or detected team
change was published during the last 72 hours. Click either badge to see the
details without leaving the table.

The updater is intentionally safe before the regular season begins: if 2026
regular-season files have not been published, it keeps the existing 2025
baseline and exits without replacing it. Once current data is available, the
Offensive Statistics page switches to 2026 actual totals and the Defensive
Statistics and Weekly Matchup pages use the refreshed 2026 baseline.

## Files updated automatically

Daily Player Research:

- `data/sleeper_players_cache.json`
- `data/nfl_players_2026.json`
- `data/player_research_daily_status.json`
- `data/player_news_index.json`

Weekly statistics:

- `data/nfl_player_stats_2026.json`
- `data/nfl_defensive_stats_current.json`

No FantasyPros key or paid data subscription is required for this refresh.

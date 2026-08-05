# Gridiron IQ 2025 Player Import Fix

## Fixed issue

The Player Research database importer previously discovered nflverse release
assets through `api.github.com`. That request could return HTTP 403 when
GitHub's unauthenticated rate limit was exhausted on Render's shared outbound
IP.

The corrected `player_research_db.py` now builds the official nflverse release
asset URLs directly. It no longer calls the GitHub API for the 2025 import.

## Files to replace

At minimum, replace this file in the root of your project:

- `player_research_db.py`

The supplied `app.py` is your uploaded `app(5).py`, renamed correctly. The ZIP
also includes the other uploaded backend modules and the Gridiron IQ engine
folder.

## Deploy

1. Back up your current repository.
2. Copy the corrected files into the root of the repository.
3. Commit and push to GitHub.
4. In Render, deploy the latest commit.
5. Confirm `GRIDIRON_DATA_DIR=/var/data` when using a persistent disk.
6. Click the 2025 Player Research database update again.

## Optional Render shell test

```bash
python build_player_research_db.py --season 2025
```

The command should import the season without requesting
`api.github.com/repos/nflverse/...`.

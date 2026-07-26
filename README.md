# Gridiron IQ ESPN Upgrade

This version makes the Command Center and Draft Center use the synced ESPN league snapshot.

## What changed
- ESPN league settings are saved after sync.
- Real teams, records, points, and rosters are saved when ESPN provides them.
- Chad's Team is detected automatically by team name.
- Command Center uses the real ESPN league.
- Draft Center adjusts the board to the synced scoring format.
- `/health` reports whether an ESPN snapshot exists.
- SWID and espn_s2 are never written to disk.

## Replace in GitHub
Replace `app.py`, the `templates` folder, `static/app.css`, `static/app.js`, and `requirements.txt` with the files in this package.

Render will redeploy automatically.

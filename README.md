# Gridiron IQ — Fresh Build

A clean, Render-ready single-user fantasy football application.

## Included
- Command Center dashboard
- Draft Center with search, filters, draft tracking, and recommendations
- ESPN private-league test and sync
- Sleeper league sync
- Yahoo OAuth foundation
- Lineup Optimizer
- Waiver Assistant
- Trade Analyzer
- Matchup Analyzer
- League Intelligence
- Reports, Settings, and Help
- No login or database dependency

## Deploy on Render
1. Create a new empty GitHub repository.
2. Upload all contents of this folder to the repository root.
3. Create a new Render Web Service from that repository.
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn app:app`
6. Health check path: `/health`
7. Clear build cache and deploy.

## Yahoo environment variables
- `YAHOO_CLIENT_ID`
- `YAHOO_CLIENT_SECRET`
- `YAHOO_REDIRECT_URI=https://YOUR-APP.onrender.com/auth/yahoo/callback`

## Important
ESPN private league access requires current SWID and espn_s2 cookie values. They are used for the request and are not stored by this build.

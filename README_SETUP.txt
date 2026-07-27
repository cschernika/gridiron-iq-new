GRIDIRON IQ — FANTASYPROS API INTEGRATION

FILES TO UPLOAD / REPLACE
1. app.py
2. templates/player_research.html
3. Keep the data folder. The existing ESPN/Yahoo JSON files are included as fallback seeds.

RENDER ENVIRONMENT VARIABLE
Add exactly:
  FANTASYPROS_API_KEY = your FantasyPros API key

Do NOT paste the API key into app.py or any HTML file.

HOW TO ADD IT IN RENDER
1. Open the Gridiron IQ web service.
2. Open Environment.
3. Add environment variable:
      Key: FANTASYPROS_API_KEY
      Value: <your FantasyPros key>
4. Save changes and let Render redeploy.

HOW THE NEW SYSTEM WORKS
- Player Research, Draft Center and Mock Draft Lab continue using the shared
  _pr_adp_lookup/platform dataset architecture.
- ESPN league => PPR dataset.
- Yahoo league => Half-PPR dataset.
- "Refresh FantasyPros Data" calls the official FantasyPros API.
- A successful refresh writes a durable local snapshot:
      data/espn_adp_2026.json
      data/yahoo_adp_2026.json
- Normal page loads read the snapshot instead of hitting the API every time.
- If the API is temporarily unavailable, the last successful snapshot remains usable.
- The API key is read only from the Render environment and is never returned to the browser.

API ENDPOINTS USED
Base:
  https://api.fantasypros.com/public/v2/json

Players:
  GET /nfl/players

Consensus rankings:
  GET /nfl/2026/consensus-rankings
  Parameters: scoring and position

Projections:
  GET /nfl/2026/projections
  Parameter: position

AUTHENTICATION
Every API request sends:
  x-api-key: <FANTASYPROS_API_KEY>

IMPORTANT ABOUT PLATFORM ADP
The integration looks for explicit ESPN/Yahoo ADP fields in the API ranking rows.
It does NOT silently substitute ECR for platform ADP.
If a FantasyPros API response provides ECR but not platform-specific ADP for a
particular player, that player's ADP remains "Not loaded" while ECR/tier/projection
data can still be stored.

TEST AFTER DEPLOYMENT
1. Open Player Research.
2. Choose Gramp's Gridiron — ESPN.
3. Click Refresh FantasyPros Data.
4. Click Check ADP Status.
5. Confirm:
      api_configured: true
      player_count: > 0
      players_with_platform_adp: > 0
6. Switch to Yahoo and repeat.

If players_with_platform_adp is 0 while player_count is > 0, send the status JSON
back to ChatGPT. That means the official endpoint's current field names for
platform ADP need to be mapped; the integration intentionally will not guess them.

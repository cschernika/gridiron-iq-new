PLAYER RESEARCH — SERVER-RENDERED VERSION

Replace:
- app.py
- templates/player_research.html

Why this version is different:
The player list is rendered directly by Flask before the page loads.
It does NOT depend on JavaScript successfully calling the position endpoint just to display players.

When you open /player-research:
- All fantasy players are listed immediately.
- Click QB, RB, WR, TE, K, or DEF to reload the page with that position.
- Position pages display position-specific 2025 stats.
- Click any player row to open the detailed research panel.

This specifically addresses the problem where Player Research kept appearing unchanged.

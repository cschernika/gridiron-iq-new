Upload/replace:
- app.py
- templates/base.html
- templates/player_research.html

This separates Player Research from Draft Center.

Player Research now provides:
- Player search
- 2025 stats
- 2022-2025 career trend data when available
- 2026 Gridiron IQ projection
- Bio, team, position, age, college, experience
- Depth chart information
- Current player/injury/practice status

The running app uses public Sleeper player metadata and nflverse historical player-stat files. The first lookup can be slower while caches are created.

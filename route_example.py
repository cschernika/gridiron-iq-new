# Example 2025 refresh route.
# Adapt the route name to match your existing app.

@app.post("/api/player-research/refresh-2025")
def refresh_player_research_2025():
    try:
        rows = _pr_rows(2025, force=True)

        if not rows:
            return jsonify({
                "ok": False,
                "error": (
                    "No 2025 player rows were downloaded and no cached "
                    "2025 data was available."
                ),
            }), 502

        # Replace this with your existing snapshot/database import function.
        result = _pr_build_snapshot(
            season=2025,
            force_refresh=False,
            source_rows=rows,
        )

        return jsonify({
            "ok": True,
            "season": 2025,
            "downloaded_rows": len(rows),
            "result": result,
        })

    except Exception as exc:
        app.logger.exception("2025 player database import failed")
        return jsonify({
            "ok": False,
            "error": f"2025 database import failed: {exc}",
        }), 500

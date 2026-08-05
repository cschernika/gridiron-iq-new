# Replace your existing _pr_rows function in app.py with this version.

def _pr_rows(season, force=False):
    """
    Load nflverse player statistics.

    force=False:
        Use the cached CSV first when it exists.

    force=True:
        Download a fresh CSV and replace the cache.
        If the download fails, fall back to the existing cache.
    """
    cache = DATA_DIR / f"player_stats_{season}.csv"

    if cache.exists() and not force:
        try:
            text = cache.read_text(encoding="utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
            if rows:
                return rows
        except Exception:
            app.logger.exception("Could not read cached %s player statistics", season)

    last_error = None

    for url in _pr_urls(season):
        try:
            response = requests.get(
                url,
                timeout=60,
                headers={"User-Agent": "Gridiron-IQ/1.0"},
            )
            response.raise_for_status()

            if len(response.content) < 1000:
                last_error = RuntimeError(
                    f"Downloaded file from {url} was unexpectedly small."
                )
                continue

            text = response.content.decode("utf-8", errors="ignore")
            rows = list(csv.DictReader(io.StringIO(text)))

            if not rows:
                last_error = RuntimeError(
                    f"No player-stat rows were found in {url}."
                )
                continue

            try:
                cache.write_text(text, encoding="utf-8")
            except Exception:
                app.logger.exception(
                    "Downloaded %s statistics but could not save the cache",
                    season,
                )

            return rows

        except Exception as exc:
            last_error = exc
            app.logger.warning(
                "Could not load %s player statistics from %s: %s",
                season,
                url,
                exc,
            )

    # A failed forced refresh should not erase working cached data.
    if cache.exists():
        try:
            text = cache.read_text(encoding="utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
            if rows:
                return rows
        except Exception:
            app.logger.exception(
                "Could not use fallback cached %s statistics",
                season,
            )

    if last_error:
        app.logger.error(
            "All %s player-stat sources failed. Last error: %s",
            season,
            last_error,
        )

    return []

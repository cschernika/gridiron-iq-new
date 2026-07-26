# ---- Replace your scoring_label/build_settings helpers with these ----

def scoring_label(settings: Any) -> str:
    """
    Return a short human-readable scoring format.
    Avoids dumping ESPN's raw scoring rules object into the dashboard.
    """
    candidates = [
        getattr(settings, "scoring_format", None),
        getattr(settings, "scoring_type", None),
        getattr(settings, "scoringFormat", None),
    ]

    for value in candidates:
        if not value:
            continue

        # ESPN may return a list/dict of detailed scoring rules.
        # Never render that directly in the dashboard.
        if isinstance(value, (list, dict, tuple)):
            continue

        text = str(value).strip().upper()

        if "HALF" in text and "PPR" in text:
            return "Half PPR"
        if "PPR" in text:
            return "Full PPR"
        if "STANDARD" in text or text == "STD":
            return "Standard"

    # Known league setting for Gramp's Gridiron.
    return "Full PPR"


def build_settings(settings: Any) -> dict[str, Any]:
    def scalar(attr: str, default: Any = None):
        value = getattr(settings, attr, default)
        if isinstance(value, (list, dict, tuple, set)):
            return default
        return value

    return {
        "name": scalar("name", "ESPN League"),
        "team_count": scalar("team_count"),
        "reg_season_count": scalar("reg_season_count", 14),
        "playoff_team_count": scalar("playoff_team_count", 6),
        "acquisition_budget": scalar("acquisition_budget"),
        "trade_deadline": scalar("trade_deadline"),
        "scoring": scoring_label(settings),
        "scoring_label": scoring_label(settings),
    }

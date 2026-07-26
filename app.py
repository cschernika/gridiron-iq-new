from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import (
    Flask, flash, jsonify, redirect, render_template, request,
    session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash
from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode, urlparse

import requests

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "gridiron_iq.db"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "development-only-change-me")
app.config["JSON_SORT_KEYS"] = False


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS league_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                league_id TEXT NOT NULL,
                league_name TEXT NOT NULL,
                season INTEGER NOT NULL,
                payload TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS espn_credentials (
                user_id INTEGER PRIMARY KEY,
                league_id TEXT NOT NULL,
                season INTEGER NOT NULL,
                swid_encrypted TEXT NOT NULL,
                s2_encrypted TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS yahoo_app_credentials (
                user_id INTEGER PRIMARY KEY,
                client_id_encrypted TEXT NOT NULL,
                client_secret_encrypted TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS yahoo_tokens (
                user_id INTEGER PRIMARY KEY,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                token_type TEXT NOT NULL,
                yahoo_guid TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS yahoo_league_preferences (
                user_id INTEGER PRIMARY KEY,
                league_key TEXT NOT NULL,
                league_name TEXT NOT NULL,
                season INTEGER,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )


init_db()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_user() -> dict[str, Any] | None:
    if not session.get("user_id"):
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, email FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
    return dict(row) if row else None


def credential_cipher() -> Fernet:
    secret = app.secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return credential_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return credential_cipher().decrypt(value.encode("utf-8")).decode("utf-8")


def saved_espn_credentials(user_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            """SELECT league_id, season, swid_encrypted, s2_encrypted, updated_at
               FROM espn_credentials WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return {
            "league_id": row["league_id"],
            "season": row["season"],
            "swid": decrypt_secret(row["swid_encrypted"]),
            "espn_s2": decrypt_secret(row["s2_encrypted"]),
            "updated_at": row["updated_at"],
        }
    except InvalidToken:
        return None


def effective_espn_credentials(user_id: int) -> dict[str, Any]:
    saved = saved_espn_credentials(user_id)
    if saved:
        return saved
    return {
        "league_id": os.getenv("ESPN_LEAGUE_ID", "").strip(),
        "season": int(os.getenv("ESPN_SEASON", "2026").strip() or "2026"),
        "swid": os.getenv("ESPN_SWID", "").strip(),
        "espn_s2": os.getenv("ESPN_S2", "").strip(),
        "updated_at": None,
    }



YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_FANTASY_URL = "https://fantasysports.yahooapis.com/fantasy/v2"


def saved_yahoo_app(user_id: int) -> dict[str, str] | None:
    with db() as conn:
        row = conn.execute(
            """SELECT client_id_encrypted, client_secret_encrypted, redirect_uri, updated_at
               FROM yahoo_app_credentials WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return {
            "client_id": decrypt_secret(row["client_id_encrypted"]),
            "client_secret": decrypt_secret(row["client_secret_encrypted"]),
            "redirect_uri": row["redirect_uri"],
            "updated_at": row["updated_at"],
        }
    except InvalidToken:
        return None


def effective_yahoo_app(user_id: int) -> dict[str, str]:
    saved = saved_yahoo_app(user_id)
    if saved:
        return saved
    return {
        "client_id": os.getenv("YAHOO_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("YAHOO_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv(
            "YAHOO_REDIRECT_URI",
            "http://127.0.0.1:8000/auth/yahoo/callback",
        ).strip(),
        "updated_at": "",
    }


def saved_yahoo_token(user_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            """SELECT access_token_encrypted, refresh_token_encrypted, expires_at,
                      token_type, yahoo_guid, updated_at
               FROM yahoo_tokens WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return {
            "access_token": decrypt_secret(row["access_token_encrypted"]),
            "refresh_token": decrypt_secret(row["refresh_token_encrypted"]),
            "expires_at": int(row["expires_at"]),
            "token_type": row["token_type"],
            "yahoo_guid": row["yahoo_guid"],
            "updated_at": row["updated_at"],
        }
    except InvalidToken:
        return None


def store_yahoo_token(user_id: int, token: dict[str, Any]) -> None:
    existing = saved_yahoo_token(user_id)
    refresh_token = token.get("refresh_token") or (existing or {}).get("refresh_token")
    if not refresh_token:
        raise ValueError("Yahoo did not return a refresh token.")
    expires_at = int(time.time()) + int(token.get("expires_in", 3600)) - 60
    now = datetime.utcnow().isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO yahoo_tokens
               (user_id, access_token_encrypted, refresh_token_encrypted, expires_at,
                token_type, yahoo_guid, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 access_token_encrypted=excluded.access_token_encrypted,
                 refresh_token_encrypted=excluded.refresh_token_encrypted,
                 expires_at=excluded.expires_at,
                 token_type=excluded.token_type,
                 yahoo_guid=excluded.yahoo_guid,
                 updated_at=excluded.updated_at""",
            (
                user_id,
                encrypt_secret(token["access_token"]),
                encrypt_secret(refresh_token),
                expires_at,
                token.get("token_type", "bearer"),
                token.get("xoauth_yahoo_guid"),
                now,
            ),
        )


def yahoo_access_token(user_id: int) -> str:
    token = saved_yahoo_token(user_id)
    if not token:
        raise RuntimeError("Yahoo is not connected.")
    if token["expires_at"] > int(time.time()):
        return token["access_token"]

    credentials = effective_yahoo_app(user_id)
    if not credentials["client_id"] or not credentials["client_secret"]:
        raise RuntimeError("Yahoo application credentials are missing.")

    response = requests.post(
        YAHOO_TOKEN_URL,
        auth=(credentials["client_id"], credentials["client_secret"]),
        data={
            "grant_type": "refresh_token",
            "redirect_uri": credentials["redirect_uri"],
            "refresh_token": token["refresh_token"],
        },
        timeout=25,
    )
    if not response.ok:
        raise RuntimeError(f"Yahoo token refresh failed: {response.text[:300]}")
    refreshed = response.json()
    store_yahoo_token(user_id, refreshed)
    return refreshed["access_token"]


def yahoo_api_get(user_id: int, path: str) -> dict[str, Any]:
    response = requests.get(
        f"{YAHOO_FANTASY_URL}/{path}",
        headers={"Authorization": f"Bearer {yahoo_access_token(user_id)}"},
        params={"format": "json"},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Yahoo API error {response.status_code}: {response.text[:400]}")
    return response.json()


def collect_yahoo_leagues(value: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if value.get("league_key") and value.get("name"):
            key = str(value["league_key"])
            if not any(item["league_key"] == key for item in found):
                found.append({
                    "league_key": key,
                    "league_id": value.get("league_id", ""),
                    "name": value.get("name", "Yahoo League"),
                    "season": value.get("season"),
                    "url": value.get("url", ""),
                    "num_teams": value.get("num_teams"),
                    "current_week": value.get("current_week"),
                })
        for child in value.values():
            collect_yahoo_leagues(child, found)
    elif isinstance(value, list):
        for child in value:
            collect_yahoo_leagues(child, found)


def collect_yahoo_teams(value: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if value.get("team_key") and value.get("name"):
            key = str(value["team_key"])
            if not any(item["team_key"] == key for item in found):
                managers = []
                manager_data = value.get("managers")
                if manager_data:
                    collect_strings_by_key(manager_data, "nickname", managers)
                found.append({
                    "team_key": key,
                    "team_id": value.get("team_id"),
                    "name": value.get("name", "Yahoo Team"),
                    "managers": managers,
                    "url": value.get("url", ""),
                    "number_of_moves": value.get("number_of_moves"),
                    "number_of_trades": value.get("number_of_trades"),
                })
        for child in value.values():
            collect_yahoo_teams(child, found)
    elif isinstance(value, list):
        for child in value:
            collect_yahoo_teams(child, found)


def collect_strings_by_key(value: Any, target_key: str, found: list[str]) -> None:
    if isinstance(value, dict):
        if target_key in value and isinstance(value[target_key], (str, int, float)):
            item = str(value[target_key])
            if item not in found:
                found.append(item)
        for child in value.values():
            collect_strings_by_key(child, target_key, found)
    elif isinstance(value, list):
        for child in value:
            collect_strings_by_key(child, target_key, found)


def yahoo_selected_league(user_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            """SELECT league_key, league_name, season, updated_at
               FROM yahoo_league_preferences WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def normalize_https_base_url(value: str) -> str:
    """Return a clean HTTPS origin without a trailing slash."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Enter an HTTPS address.")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        raise ValueError("Yahoo requires an HTTPS address.")
    if not parsed.netloc:
        raise ValueError("The HTTPS address is not valid.")
    return f"https://{parsed.netloc}".rstrip("/")


def yahoo_callback_from_base(value: str) -> str:
    return normalize_https_base_url(value) + "/auth/yahoo/callback"


def active_ngrok_https_url() -> str | None:
    """Discover a running local ngrok tunnel from ngrok's local API."""
    try:
        response = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=3)
        response.raise_for_status()
        tunnels = response.json().get("tunnels", [])
        https_urls = [
            item.get("public_url", "")
            for item in tunnels
            if str(item.get("public_url", "")).startswith("https://")
        ]
        return https_urls[0].rstrip("/") if https_urls else None
    except Exception:
        return None

def demo_intelligence() -> dict[str, Any]:
    return {
        "team_strength": 86,
        "team_rank": 3,
        "playoff_probability": 74,
        "championship_probability": 18,
        "lineup_gain": 7.1,
        "trade_opportunities": 4,
        "power_rankings": [
            {"rank": 1, "team": "Sunday Crushers", "rating": 91, "playoffs": 82},
            {"rank": 2, "team": "Fourth & Long", "rating": 88, "playoffs": 77},
            {"rank": 3, "team": "Your Team", "rating": 86, "playoffs": 74},
            {"rank": 4, "team": "Gridiron Kings", "rating": 83, "playoffs": 66},
        ],
        "manager_profiles": [
            {"manager": "Mike", "pattern": "Drafts quarterbacks early", "need": "RB2", "likelihood": 78},
            {"manager": "Sarah", "pattern": "Overvalues rookies", "need": "WR depth", "likelihood": 64},
            {"manager": "Chris", "pattern": "Holds players too long", "need": "TE", "likelihood": 31},
            {"manager": "Dan", "pattern": "Chases last week's points", "need": "QB", "likelihood": 72},
        ],
        "lineup": [
            {"slot": "QB", "player": "Jalen Hurts", "points": 24.1},
            {"slot": "RB", "player": "Josh Jacobs", "points": 17.6},
            {"slot": "RB", "player": "Jordan Mason", "points": 14.8},
            {"slot": "WR", "player": "Puka Nacua", "points": 18.9},
            {"slot": "WR", "player": "DeVonta Smith", "points": 14.2},
            {"slot": "TE", "player": "Dalton Kincaid", "points": 10.7},
            {"slot": "FLEX", "player": "Marcus Reed", "points": 12.4},
            {"slot": "DST", "player": "Baltimore", "points": 6.0},
        ],
        "waivers": [
            {"player": "Marcus Reed", "position": "WR", "faab": "$7–$10", "grade": "A"},
            {"player": "Ty Chandler", "position": "RB", "faab": "$4–$7", "grade": "B+"},
            {"player": "Luke Musgrave", "position": "TE", "faab": "$1–$3", "grade": "B"},
        ],
    }


@app.get("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, email and a password of at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        try:
            with db() as conn:
                cursor = conn.execute(
                    "INSERT INTO users(name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (name, email, generate_password_hash(password), datetime.utcnow().isoformat()),
                )
                session["user_id"] = cursor.lastrowid
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "error")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        flash("The email or password was not recognized.", "error")
    return render_template("auth.html", mode="login")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/app")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        user=current_user(),
        analytics=demo_intelligence(),
    )


@app.get("/api/health")
def health():
    configured = False
    if session.get("user_id"):
        creds = effective_espn_credentials(session["user_id"])
        configured = all(creds.get(k) for k in ("league_id", "season", "swid", "espn_s2"))
    else:
        configured = all(
            os.getenv(k)
            for k in ("ESPN_LEAGUE_ID", "ESPN_SEASON", "ESPN_SWID", "ESPN_S2")
        )
    return jsonify(
        ok=True,
        server="Gridiron IQ V6",
        espn_configured=configured,
        database=str(DB_PATH.name),
    )


@app.post("/api/espn/sync")
@login_required
def sync_espn():
    credentials = effective_espn_credentials(session["user_id"])
    league_id = str(credentials.get("league_id", "")).strip()
    season = str(credentials.get("season", "2026")).strip()
    swid = str(credentials.get("swid", "")).strip()
    espn_s2 = str(credentials.get("espn_s2", "")).strip()

    missing = [
        key for key, value in {
            "ESPN_LEAGUE_ID": league_id,
            "ESPN_SEASON": season,
            "ESPN_SWID": swid,
            "ESPN_S2": espn_s2,
        }.items() if not value
    ]
    if missing:
        return jsonify(error=f"Missing settings: {', '.join(missing)}"), 400

    try:
        from espn_api.football import League

        league = League(
            league_id=int(league_id),
            year=int(season),
            swid=swid,
            espn_s2=espn_s2,
        )
        teams = []
        roster_count = 0
        for team in league.teams:
            roster = []
            for player in team.roster:
                roster.append({
                    "name": getattr(player, "name", "Unknown"),
                    "position": getattr(player, "position", ""),
                    "pro_team": getattr(player, "proTeam", ""),
                })
            roster_count += len(roster)
            teams.append({
                "team_name": getattr(team, "team_name", "Unnamed team"),
                "owner": getattr(team, "owner", ""),
                "wins": getattr(team, "wins", 0),
                "losses": getattr(team, "losses", 0),
                "roster": roster,
            })

        payload = {
            "league": {
                "id": league_id,
                "name": getattr(league.settings, "name", "ESPN League"),
                "season": int(season),
                "team_count": len(teams),
                "roster_count": roster_count,
                "current_week": getattr(league, "current_week", 0),
            },
            "teams": teams,
        }

        with db() as conn:
            conn.execute(
                """INSERT INTO league_snapshots
                   (user_id, platform, league_id, league_name, season, payload, synced_at)
                   VALUES (?, 'ESPN', ?, ?, ?, ?, ?)""",
                (
                    session["user_id"],
                    league_id,
                    payload["league"]["name"],
                    int(season),
                    json.dumps(payload),
                    datetime.utcnow().isoformat(),
                ),
            )
        return jsonify(payload)
    except Exception as exc:
        app.logger.exception("ESPN sync failed")
        return jsonify(
            error="Unable to connect to ESPN.",
            detail=str(exc),
            suggestion=(
                "Confirm the final manager has joined, then refresh the SWID and espn_s2 "
                "from the ESPN account that can open this league."
            ),
        ), 400


@app.get("/api/espn/connection")
@login_required
def espn_connection():
    credentials = effective_espn_credentials(session["user_id"])
    configured = all(credentials.get(k) for k in ("league_id", "season", "swid", "espn_s2"))
    return jsonify(
        configured=configured,
        league_id=credentials.get("league_id", ""),
        season=credentials.get("season", 2026),
        saved_locally=saved_espn_credentials(session["user_id"]) is not None,
        updated_at=credentials.get("updated_at"),
    )


@app.post("/api/espn/connection")
@login_required
def save_espn_connection():
    payload = request.get_json(silent=True) or {}
    league_id = str(payload.get("league_id", "")).strip()
    season = str(payload.get("season", "2026")).strip()
    swid = str(payload.get("swid", "")).strip()
    espn_s2 = str(payload.get("espn_s2", "")).strip()

    if not all((league_id, season, swid, espn_s2)):
        return jsonify(error="League ID, season, SWID and espn_s2 are all required."), 400
    try:
        int(league_id)
        int(season)
    except ValueError:
        return jsonify(error="League ID and season must contain numbers only."), 400

    now = datetime.utcnow().isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO espn_credentials
               (user_id, league_id, season, swid_encrypted, s2_encrypted, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 league_id=excluded.league_id,
                 season=excluded.season,
                 swid_encrypted=excluded.swid_encrypted,
                 s2_encrypted=excluded.s2_encrypted,
                 updated_at=excluded.updated_at""",
            (
                session["user_id"],
                league_id,
                int(season),
                encrypt_secret(swid),
                encrypt_secret(espn_s2),
                now,
            ),
        )
    return jsonify(ok=True, message="ESPN connection saved securely on this computer.")


@app.delete("/api/espn/connection")
@login_required
def delete_espn_connection():
    with db() as conn:
        conn.execute("DELETE FROM espn_credentials WHERE user_id = ?", (session["user_id"],))
    return jsonify(ok=True, message="Saved ESPN credentials were removed.")


@app.post("/api/espn/test")
@login_required
def test_espn_connection():
    payload = request.get_json(silent=True) or {}
    if payload:
        credentials = {
            "league_id": str(payload.get("league_id", "")).strip(),
            "season": str(payload.get("season", "2026")).strip(),
            "swid": str(payload.get("swid", "")).strip(),
            "espn_s2": str(payload.get("espn_s2", "")).strip(),
        }
    else:
        credentials = effective_espn_credentials(session["user_id"])

    if not all(credentials.get(k) for k in ("league_id", "season", "swid", "espn_s2")):
        return jsonify(error="Complete all four ESPN connection fields first."), 400

    try:
        from espn_api.football import League
        league = League(
            league_id=int(credentials["league_id"]),
            year=int(credentials["season"]),
            swid=credentials["swid"],
            espn_s2=credentials["espn_s2"],
        )
        return jsonify(
            ok=True,
            league_name=getattr(league.settings, "name", "ESPN League"),
            team_count=len(league.teams),
            message="Connection successful.",
        )
    except Exception as exc:
        return jsonify(
            error="ESPN rejected the connection.",
            detail=str(exc),
            suggestion="Confirm the league is active and refresh both ESPN cookie values.",
        ), 400


@app.get("/api/ngrok/status")
@login_required
def ngrok_status():
    public_url = active_ngrok_https_url()
    if not public_url:
        return jsonify(
            running=False,
            message="No active ngrok HTTPS tunnel was detected.",
            help="Start ngrok with: ngrok http 8000",
        )
    return jsonify(
        running=True,
        public_url=public_url,
        redirect_uri=yahoo_callback_from_base(public_url),
        message="Active ngrok HTTPS tunnel detected.",
    )


@app.post("/api/yahoo/validate-redirect")
@login_required
def validate_yahoo_redirect():
    payload = request.get_json(silent=True) or {}
    value = str(payload.get("url") or payload.get("redirect_uri") or "").strip()
    try:
        if value.endswith("/auth/yahoo/callback"):
            parsed = urlparse(value)
            if parsed.scheme.lower() != "https" or not parsed.netloc:
                raise ValueError("Yahoo requires a valid HTTPS callback address.")
            redirect_uri = f"https://{parsed.netloc}/auth/yahoo/callback"
        else:
            redirect_uri = yahoo_callback_from_base(value)
        return jsonify(
            ok=True,
            redirect_uri=redirect_uri,
            message="This HTTPS callback format is valid for Gridiron IQ.",
        )
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400


@app.get("/api/yahoo/status")
@login_required
def yahoo_status():
    user_id = session["user_id"]
    credentials = effective_yahoo_app(user_id)
    token = saved_yahoo_token(user_id)
    selected = yahoo_selected_league(user_id)
    return jsonify(
        app_configured=bool(credentials["client_id"] and credentials["client_secret"]),
        redirect_uri=credentials["redirect_uri"],
        connected=token is not None,
        selected_league=selected,
        credentials_saved_locally=saved_yahoo_app(user_id) is not None,
    )


@app.post("/api/yahoo/app-credentials")
@login_required
def save_yahoo_app_credentials():
    payload = request.get_json(silent=True) or {}
    client_id = str(payload.get("client_id", "")).strip()
    client_secret = str(payload.get("client_secret", "")).strip()
    redirect_uri = str(payload.get("redirect_uri", "")).strip()
    if not all((client_id, client_secret, redirect_uri)):
        return jsonify(error="Client ID, Client Secret and Redirect URI are required."), 400
    try:
        parsed_redirect = urlparse(redirect_uri)
        if parsed_redirect.scheme.lower() != "https" or not parsed_redirect.netloc:
            raise ValueError("Yahoo requires an HTTPS Redirect URI.")
        if parsed_redirect.path.rstrip("/") != "/auth/yahoo/callback":
            raise ValueError("The Redirect URI must end with /auth/yahoo/callback.")
        redirect_uri = f"https://{parsed_redirect.netloc}/auth/yahoo/callback"
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    with db() as conn:
        conn.execute(
            """INSERT INTO yahoo_app_credentials
               (user_id, client_id_encrypted, client_secret_encrypted, redirect_uri, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 client_id_encrypted=excluded.client_id_encrypted,
                 client_secret_encrypted=excluded.client_secret_encrypted,
                 redirect_uri=excluded.redirect_uri,
                 updated_at=excluded.updated_at""",
            (
                session["user_id"],
                encrypt_secret(client_id),
                encrypt_secret(client_secret),
                redirect_uri,
                datetime.utcnow().isoformat(),
            ),
        )
    return jsonify(ok=True, message="Yahoo application credentials saved securely.")


@app.delete("/api/yahoo/app-credentials")
@login_required
def delete_yahoo_app_credentials():
    with db() as conn:
        conn.execute("DELETE FROM yahoo_app_credentials WHERE user_id = ?", (session["user_id"],))
        conn.execute("DELETE FROM yahoo_tokens WHERE user_id = ?", (session["user_id"],))
        conn.execute("DELETE FROM yahoo_league_preferences WHERE user_id = ?", (session["user_id"],))
    return jsonify(ok=True, message="Yahoo credentials and connection were removed.")


@app.get("/auth/yahoo")
@login_required
def yahoo_authorize():
    credentials = effective_yahoo_app(session["user_id"])
    if not credentials["client_id"] or not credentials["client_secret"]:
        flash("Save your Yahoo Client ID and Client Secret first.", "error")
        return redirect(url_for("dashboard") + "#settings")
    if not credentials["redirect_uri"].startswith("https://"):
        flash("Yahoo requires HTTPS. Start ngrok, detect the HTTPS address, and save it first.", "error")
        return redirect(url_for("dashboard") + "#settings")

    state = secrets.token_urlsafe(32)
    session["yahoo_oauth_state"] = state
    params = {
        "client_id": credentials["client_id"],
        "redirect_uri": credentials["redirect_uri"],
        "response_type": "code",
        "state": state,
        "language": "en-us",
    }
    return redirect(f"{YAHOO_AUTH_URL}?{urlencode(params)}")


@app.get("/auth/yahoo/callback")
@login_required
def yahoo_callback():
    if request.args.get("error"):
        flash(f"Yahoo authorization was declined: {request.args.get('error_description', request.args['error'])}", "error")
        return redirect(url_for("dashboard") + "#settings")

    state = request.args.get("state", "")
    expected_state = session.pop("yahoo_oauth_state", "")
    if not expected_state or not secrets.compare_digest(state, expected_state):
        flash("Yahoo connection could not be verified. Please try again.", "error")
        return redirect(url_for("dashboard") + "#settings")

    code = request.args.get("code", "")
    credentials = effective_yahoo_app(session["user_id"])
    response = requests.post(
        YAHOO_TOKEN_URL,
        auth=(credentials["client_id"], credentials["client_secret"]),
        data={
            "grant_type": "authorization_code",
            "redirect_uri": credentials["redirect_uri"],
            "code": code,
        },
        timeout=25,
    )
    if not response.ok:
        flash(f"Yahoo token exchange failed: {response.text[:250]}", "error")
        return redirect(url_for("dashboard") + "#settings")

    try:
        store_yahoo_token(session["user_id"], response.json())
        flash("Yahoo connected successfully. Select your league below.", "success")
    except Exception as exc:
        flash(f"Yahoo connected, but the token could not be saved: {exc}", "error")
    return redirect(url_for("dashboard") + "#settings")


@app.post("/api/yahoo/disconnect")
@login_required
def yahoo_disconnect():
    with db() as conn:
        conn.execute("DELETE FROM yahoo_tokens WHERE user_id = ?", (session["user_id"],))
        conn.execute("DELETE FROM yahoo_league_preferences WHERE user_id = ?", (session["user_id"],))
    return jsonify(ok=True, message="Yahoo was disconnected.")


@app.get("/api/yahoo/leagues")
@login_required
def yahoo_leagues():
    try:
        raw = yahoo_api_get(
            session["user_id"],
            "users;use_login=1/games;game_keys=nfl/leagues",
        )
        leagues: list[dict[str, Any]] = []
        collect_yahoo_leagues(raw, leagues)
        leagues.sort(key=lambda item: int(item.get("season") or 0), reverse=True)
        return jsonify(leagues=leagues)
    except Exception as exc:
        app.logger.exception("Yahoo league discovery failed")
        return jsonify(error="Unable to load Yahoo leagues.", detail=str(exc)), 400


@app.post("/api/yahoo/select-league")
@login_required
def yahoo_select_league():
    payload = request.get_json(silent=True) or {}
    league_key = str(payload.get("league_key", "")).strip()
    league_name = str(payload.get("league_name", "")).strip()
    season = payload.get("season")
    if not league_key or not league_name:
        return jsonify(error="Choose a Yahoo league first."), 400
    with db() as conn:
        conn.execute(
            """INSERT INTO yahoo_league_preferences
               (user_id, league_key, league_name, season, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 league_key=excluded.league_key,
                 league_name=excluded.league_name,
                 season=excluded.season,
                 updated_at=excluded.updated_at""",
            (
                session["user_id"],
                league_key,
                league_name,
                int(season) if str(season or "").isdigit() else None,
                datetime.utcnow().isoformat(),
            ),
        )
    return jsonify(ok=True, message=f"{league_name} selected.")


@app.post("/api/yahoo/sync")
@login_required
def sync_yahoo():
    selected = yahoo_selected_league(session["user_id"])
    if not selected:
        return jsonify(error="Select a Yahoo league before syncing."), 400
    try:
        league_key = selected["league_key"]
        raw = yahoo_api_get(
            session["user_id"],
            f"league/{league_key}/teams;out=standings,roster",
        )
        teams: list[dict[str, Any]] = []
        collect_yahoo_teams(raw, teams)
        payload = {
            "league": {
                "id": league_key,
                "name": selected["league_name"],
                "season": selected.get("season") or datetime.utcnow().year,
                "team_count": len(teams),
                "platform": "Yahoo",
            },
            "teams": teams,
            "raw_available": True,
        }
        with db() as conn:
            conn.execute(
                """INSERT INTO league_snapshots
                   (user_id, platform, league_id, league_name, season, payload, synced_at)
                   VALUES (?, 'Yahoo', ?, ?, ?, ?, ?)""",
                (
                    session["user_id"],
                    league_key,
                    selected["league_name"],
                    int(payload["league"]["season"]),
                    json.dumps(payload),
                    datetime.utcnow().isoformat(),
                ),
            )
        return jsonify(payload)
    except Exception as exc:
        app.logger.exception("Yahoo sync failed")
        return jsonify(
            error="Unable to sync the Yahoo league.",
            detail=str(exc),
            suggestion="Reconnect Yahoo, confirm Fantasy Sports access, and verify the Redirect URI exactly matches your Yahoo app.",
        ), 400


@app.get("/api/latest-league")
@login_required
def latest_league():
    with db() as conn:
        row = conn.execute(
            """SELECT payload, synced_at FROM league_snapshots
               WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
            (session["user_id"],),
        ).fetchone()
    if not row:
        return jsonify(error="No league has been synced yet."), 404
    payload = json.loads(row["payload"])
    payload["synced_at"] = row["synced_at"]
    return jsonify(payload)


@app.get("/api/intelligence")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="127.0.0.1", port=port, debug=False)

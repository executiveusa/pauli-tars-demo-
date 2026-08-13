"""Read-only Trail Mixx/AzuraCast adapter for BARS.

Phase 3 starts with the public AzuraCast now-playing endpoint only. This module
contains no write methods and accepts no request-supplied target URL: the owner
must configure the trusted Trail Mixx base URL locally in config.json.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_TIMEOUT_SECONDS = 8


class TrailMixxError(RuntimeError):
    pass


def _base_url(config: dict) -> str:
    raw = str((config or {}).get("base_url") or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TrailMixxError("Trail Mixx base_url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise TrailMixxError("Trail Mixx base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise TrailMixxError("Trail Mixx base_url must not contain query or fragment data")
    return raw


def status(config: dict) -> dict:
    """Configuration state only; does not claim the remote station is healthy."""
    try:
        base = _base_url(config)
    except TrailMixxError as exc:
        return {"configured": False, "state": "invalid", "error": str(exc)}
    return {"configured": bool(base), "state": "configured" if base else "unconfigured"}


def _read_json(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BARS-Trail-Mixx/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    if int(declared) > MAX_RESPONSE_BYTES:
                        raise TrailMixxError("Trail Mixx response exceeded size limit")
                except ValueError:
                    pass
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise TrailMixxError("Trail Mixx response exceeded size limit")
    except urllib.error.HTTPError as exc:
        raise TrailMixxError(f"Trail Mixx returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TrailMixxError(f"Trail Mixx connection failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise TrailMixxError("Trail Mixx request timed out") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrailMixxError("Trail Mixx returned invalid JSON") from exc


def _song(row: dict) -> dict:
    np = row.get("now_playing") if isinstance(row.get("now_playing"), dict) else {}
    song = np.get("song") if isinstance(np.get("song"), dict) else {}
    listeners = row.get("listeners") if isinstance(row.get("listeners"), dict) else {}
    station = row.get("station") if isinstance(row.get("station"), dict) else {}
    return {
        "station": {
            "id": station.get("id"),
            "name": station.get("name"),
            "shortcode": station.get("shortcode"),
        },
        "online": bool(row.get("is_online")),
        "now_playing": {
            "title": song.get("title"),
            "artist": song.get("artist"),
            "album": song.get("album"),
            "played_at": np.get("played_at"),
            "duration": np.get("duration"),
            "elapsed": np.get("elapsed"),
            "remaining": np.get("remaining"),
        },
        "listeners": {
            "current": listeners.get("current"),
            "unique": listeners.get("unique"),
            "total": listeners.get("total"),
        },
    }


def now_playing(config: dict) -> dict:
    """Read and normalize the public `/api/nowplaying` response."""
    base = _base_url(config)
    if not base:
        return {
            "configured": False,
            "connected": False,
            "source": "trail_mixx_public_nowplaying",
            "stations": [],
            "error": "Trail Mixx base_url is not configured",
        }

    payload = _read_json(f"{base}/api/nowplaying")
    rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else None
    if rows is None:
        raise TrailMixxError("Trail Mixx now-playing response had an unexpected shape")

    stations = [_song(row) for row in rows if isinstance(row, dict)]
    if len(stations) != len(rows):
        raise TrailMixxError("Trail Mixx now-playing response contained invalid station rows")

    configured_station = str((config or {}).get("station_id") or "").strip()
    if configured_station:
        stations = [
            row for row in stations
            if str(row["station"].get("id") or "") == configured_station
            or str(row["station"].get("shortcode") or "") == configured_station
        ]

    return {
        "configured": True,
        "connected": True,
        "source": "trail_mixx_public_nowplaying",
        "endpoint": "/api/nowplaying",
        "station_filter": configured_station or None,
        "stations": stations,
    }

"""Philips Hue link — the room reacts to TARS.

Amber wash while he speaks, red flash on a failed sortie, amber blink on
mission complete, brief flare on deploy. Local bridge v1 API, stdlib only.
Silent no-op without a bridge. Pairing state: tars-hue.json — and if absent,
falls back READ-ONLY to Jarvis's jarvis-hue.json so an already-paired bridge
just works (same one-place-to-pair rule as the API keys).
"""
import json, os, threading, urllib.request

_CFG = {}
_ROOT = "."
_LOCK = threading.Lock()
_SAVED = {}
_SPEAKING = [False]

_JARVIS_HUE = os.path.expanduser(
    "~/Documents/Claude Code/projects/2026-06-video-claude-os/packages/brain-studio/jarvis-hue.json")

AMBER = {"hue": 6300, "sat": 220}     # TARS amber, not Jarvis emerald
RED = {"hue": 0, "sat": 254}


def init(cfg, root):
    global _CFG, _ROOT
    _CFG, _ROOT = dict(cfg or {}), root


def _stored():
    for path in (os.path.join(_ROOT, "tars-hue.json"), _JARVIS_HUE):
        try:
            if os.path.exists(path):
                return json.load(open(path))
        except Exception:
            pass
    return {}


def _conn():
    st = _stored()
    ip = _CFG.get("bridge_ip") or st.get("bridge_ip")
    key = _CFG.get("app_key") or st.get("app_key")
    lights = _CFG.get("lights") or st.get("lights") or []
    return (ip, key, lights) if ip and key else (None, None, [])


def status():
    ip, _k, lights = _conn()
    return {"state": "ready" if ip else "absent", "lights": len(lights)}


def _req(url, data=None, method=None, timeout=3):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method or ("PUT" if body else "GET"))
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp)


def _put(ip, key, lid, state):
    try:
        _req(f"http://{ip}/api/{key}/lights/{lid}/state", state)
    except Exception:
        pass


def _states(ip, key, lights):
    out = {}
    for lid in lights:
        try:
            s = _req(f"http://{ip}/api/{key}/lights/{lid}")["state"]
            out[lid] = {k: s[k] for k in ("on", "bri", "hue", "sat") if k in s}
        except Exception:
            pass
    return out


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


def _speak_start():
    ip, key, lights = _conn()
    if not ip or _SPEAKING[0]:
        return
    _SPEAKING[0] = True

    def go():
        with _LOCK:
            _SAVED.clear()
            _SAVED.update(_states(ip, key, lights))
            for lid in lights:
                prev = _SAVED.get(lid, {})
                _put(ip, key, lid, {"on": True, **AMBER,
                                    "bri": min(254, prev.get("bri", 160) + 50),
                                    "transitiontime": 2})
    _spawn(go)


def _speak_end():
    ip, key, lights = _conn()
    if not ip or not _SPEAKING[0]:
        return
    _SPEAKING[0] = False

    def go():
        with _LOCK:
            for lid in lights:
                prev = _SAVED.get(lid)
                if prev:
                    _put(ip, key, lid, {**prev, "transitiontime": 4})
    _spawn(go)


def _flash(color, times=2):
    ip, key, lights = _conn()
    if not ip:
        return

    def go():
        import time as _t
        with _LOCK:
            saved = _states(ip, key, lights)
            for _ in range(times):
                for lid in lights:
                    _put(ip, key, lid, {"on": True, **color, "bri": 254, "transitiontime": 0})
                _t.sleep(.35)
                for lid in lights:
                    _put(ip, key, lid, {"bri": 40, "transitiontime": 0})
                _t.sleep(.25)
            for lid in lights:
                prev = saved.get(lid)
                if prev:
                    _put(ip, key, lid, {**prev, "transitiontime": 4})
    _spawn(go)


def event(name):
    """speak_start | speak_end | fail | complete | deploy — all fire-and-forget."""
    if name == "speak_start":
        _speak_start()
    elif name == "speak_end":
        _speak_end()
    elif name == "fail":
        _flash(RED, 3)
    elif name == "complete":
        _flash(AMBER, 1)
    elif name == "deploy":
        _flash(AMBER, 1)

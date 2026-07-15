"""TARS HANDS — permission-gated REAL DESKTOP takeover (cross-platform: macOS + Windows).

"Permission to take the controls, sir?" → "go ahead" → TARS drives your actual machine
(your real mouse + keyboard on your real screen) via Claude's computer-use vision loop:
screenshot → Claude picks an action → native input events execute it on the live desktop →
screenshot → repeat, until Claude says done, the step cap hits, you press STOP, or you
grab the physical mouse. Never clicks a payment/purchase/delete final button — fills and
stops for you.

PLATFORM SUPPORT:
  macOS   → Quartz CGEvents (pyobjc) + screencapture + sips
  Windows → pyautogui (mouse/keyboard) + mss (screenshots) + PIL (resize)

This is NOT the Playwright browser mission (that opens a separate throwaway browser).
This is your own screen.

macOS:   Requires TCC grants the FIRST time: Screen Recording + Accessibility.
Windows: No special setup needed. pyautogui + mss install via pip.
State is in-memory only.
"""
import platform as _platform

IS_MAC = _platform.system() == "Darwin"
IS_WIN = _platform.system() == "Windows"
import base64, json, os, subprocess, tempfile, threading, time, urllib.error, urllib.parse, urllib.request

CTX = {}                    # init() fills: key, model, persona, mem, presence, log
RUN = {"active": False, "stop": False, "task": "", "started": 0.0}
EVENTS = []                 # normalized [{ts,kind,text}] the client polls; kind: say|action|done|error
EV_LOCK = threading.Lock()
PENDING = {}                # confirm_id -> task awaiting "go ahead"

MAX_STEPS = 40
MAX_SECONDS = 300
SEND_W = 1280               # downscale screenshots to this width — best click accuracy + cheap tokens
# Each computer-use step is a full multimodal round trip, so per-step model latency
# dominates. The tool VERSION is pinned per model (probed live 2026-07-09):
#   haiku  → computer_20250124   sonnet/opus → computer_20251124
# tiers: fast (Haiku, snappiest), balanced (Sonnet 5, default), smart (Opus 4.8).
SPEED_TIERS = {
    "fast":     ("claude-haiku-4-5", "computer_20250124", "computer-use-2025-01-24"),
    "balanced": ("claude-sonnet-5",  "computer_20251124", "computer-use-2025-11-24"),
    "smart":    ("claude-opus-4-8",  "computer_20251124", "computer-use-2025-11-24"),
}
SPEED = "balanced"
COMPUTER_MODEL, TOOL_TYPE, TOOL_BETA = SPEED_TIERS[SPEED]

def set_speed(tier):
    """Pick the takeover model/tool tier: fast | balanced | smart."""
    global SPEED, COMPUTER_MODEL, TOOL_TYPE, TOOL_BETA
    if tier in SPEED_TIERS:
        SPEED = tier
        COMPUTER_MODEL, TOOL_TYPE, TOOL_BETA = SPEED_TIERS[tier]
    return SPEED

DANGER = ("buy", "purchase", "pay ", "payment", "checkout", "place order", "wire ", "send money",
          "delete account", "close account", "transfer", "confirm order")

# ---------- event log ----------

def emit(kind, text):
    with EV_LOCK:
        EVENTS.append({"ts": time.time(), "kind": kind, "text": text})
        if len(EVENTS) > 400:
            del EVENTS[:200]
    if kind in ("say", "action", "done", "error") and CTX.get("log"):
        try:
            CTX["log"](kind, text)
        except Exception:
            pass

def events_since(n):
    with EV_LOCK:
        return EVENTS[max(0, n):], len(EVENTS)

# ---------- screen + input (CROSS-PLATFORM: macOS + Windows) ----------

# ── macOS implementation (Quartz / pyobjc) ──────────────────────
if IS_MAC:
    def _q():
        import Quartz
        return Quartz

    def screen_points():
        Q = _q()
        b = Q.CGDisplayBounds(Q.CGMainDisplayID())
        return int(b.size.width), int(b.size.height)

    def grab_screen():
        """(b64 jpeg, sent_w, sent_h) — fresh screenshot downscaled to SEND_W."""
        fd, raw = tempfile.mkstemp(suffix=".jpg"); os.close(fd)
        small = raw.replace(".jpg", "-s.jpg")
        try:
            r = subprocess.run(["screencapture", "-x", "-o", "-t", "jpg", "-m", raw],
                               capture_output=True, timeout=15)
            if r.returncode != 0 or not os.path.getsize(raw):
                return None, 0, 0
            subprocess.run(["sips", "--resampleWidth", str(SEND_W), raw, "--out", small],
                           capture_output=True, timeout=15)
            use = small if os.path.exists(small) else raw
            dims = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", use],
                                 capture_output=True, text=True, timeout=10).stdout
            w = h = 0
            for line in dims.splitlines():
                if "pixelWidth:" in line: w = int(line.split(":")[1])
                if "pixelHeight:" in line: h = int(line.split(":")[1])
            with open(use, "rb") as f:
                return base64.b64encode(f.read()).decode(), (w or SEND_W), (h or 800)
        except Exception:
            return None, 0, 0
        finally:
            for f in (raw, small):
                try: os.remove(f)
                except OSError: pass

    def cursor_point():
        Q = _q()
        return tuple(Q.CGEventGetLocation(Q.CGEventCreate(None)))[:2]

    def _mouse(x, y, etype, button):
        Q = _q()
        Q.CGEventPost(Q.kCGHIDEventTap, Q.CGEventCreateMouseEvent(None, etype, (x, y), button))

    def move_to(x, y):
        _mouse(x, y, _q().kCGEventMouseMoved, 0)

    def click_at(x, y, button="left", count=1):
        Q = _q()
        down = {"left": Q.kCGEventLeftMouseDown, "right": Q.kCGEventRightMouseDown,
                "middle": Q.kCGEventOtherMouseDown}[button]
        up = {"left": Q.kCGEventLeftMouseUp, "right": Q.kCGEventRightMouseUp,
              "middle": Q.kCGEventOtherMouseUp}[button]
        btn = {"left": 0, "right": 1, "middle": 2}[button]
        move_to(x, y); time.sleep(0.03)
        for i in range(count):
            d = Q.CGEventCreateMouseEvent(None, down, (x, y), btn)
            Q.CGEventSetIntegerValueField(d, Q.kCGMouseEventClickState, i + 1)
            Q.CGEventPost(Q.kCGHIDEventTap, d)
            u = Q.CGEventCreateMouseEvent(None, up, (x, y), btn)
            Q.CGEventSetIntegerValueField(u, Q.kCGMouseEventClickState, i + 1)
            Q.CGEventPost(Q.kCGHIDEventTap, u)
            time.sleep(0.04)

    def drag(x1, y1, x2, y2):
        Q = _q()
        move_to(x1, y1); time.sleep(0.03)
        _mouse(x1, y1, Q.kCGEventLeftMouseDown, 0); time.sleep(0.05)
        steps = 12
        for i in range(1, steps + 1):
            _mouse(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps,
                   Q.kCGEventLeftMouseDragged, 0)
            time.sleep(0.012)
        _mouse(x2, y2, Q.kCGEventLeftMouseUp, 0)

    def scroll(dy, dx=0):
        Q = _q()
        Q.CGEventPost(Q.kCGHIDEventTap,
                      Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 2,
                                                      int(dy), int(dx)))

    def type_text(text):
        Q = _q()
        for ch in text:
            for down in (True, False):
                e = Q.CGEventCreateKeyboardEvent(None, 0, down)
                Q.CGEventKeyboardSetUnicodeString(e, len(ch), ch)
                Q.CGEventPost(Q.kCGHIDEventTap, e)
            time.sleep(0.008)

    KEYCODE = {"return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
               "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
               "home": 115, "end": 119, "pageup": 116, "page_up": 116, "pagedown": 121,
               "page_down": 121, "forward_delete": 117, "a": 0, "s": 1, "d": 2, "f": 3, "h": 4,
               "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
               "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40,
               "n": 45, "m": 46, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26,
               "8": 28, "9": 25, "0": 29}
    MODS = {"cmd": "kCGEventFlagMaskCommand", "command": "kCGEventFlagMaskCommand",
            "meta": "kCGEventFlagMaskCommand", "super": "kCGEventFlagMaskCommand",
            "ctrl": "kCGEventFlagMaskControl", "control": "kCGEventFlagMaskControl",
            "alt": "kCGEventFlagMaskAlternate", "option": "kCGEventFlagMaskAlternate",
            "shift": "kCGEventFlagMaskShift"}

    def press_key(combo):
        Q = _q()
        parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
        if not parts: return
        kc = KEYCODE.get(parts[-1])
        if kc is None: return
        flags = 0
        for m in parts[:-1]:
            f = MODS.get(m)
            if f: flags |= getattr(Q, f)
        down = Q.CGEventCreateKeyboardEvent(None, kc, True)
        Q.CGEventSetFlags(down, flags); Q.CGEventPost(Q.kCGHIDEventTap, down)
        up = Q.CGEventCreateKeyboardEvent(None, kc, False)
        Q.CGEventSetFlags(up, flags); Q.CGEventPost(Q.kCGHIDEventTap, up)

# ── Windows implementation (pyautogui + mss + PIL) ──────────────
elif IS_WIN:
    import io as _io

    def screen_points():
        import pyautogui
        return pyautogui.size().width, pyautogui.size().height

    def grab_screen():
        """(b64 jpeg, sent_w, sent_h) — fresh screenshot downscaled to SEND_W."""
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                mon = sct.monitors[1]
                raw = sct.grab(mon)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            ratio = SEND_W / img.width
            new_h = int(img.height * ratio)
            img = img.resize((SEND_W, new_h), Image.LANCZOS)
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=82)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return b64, SEND_W, new_h
        except Exception:
            return None, 0, 0

    def cursor_point():
        import pyautogui
        p = pyautogui.position()
        return (p.x, p.y)

    def move_to(x, y):
        import pyautogui
        pyautogui.moveTo(int(x), int(y), _pause=False)

    def click_at(x, y, button="left", count=1):
        import pyautogui
        btn = "right" if button == "right" else "middle" if button == "middle" else "left"
        pyautogui.click(int(x), int(y), clicks=count, button=btn, _pause=False)
        time.sleep(0.04)

    def drag(x1, y1, x2, y2):
        import pyautogui
        pyautogui.moveTo(int(x1), int(y1), _pause=False)
        pyautogui.mouseDown(int(x1), int(y1), button="left", _pause=False)
        steps = 12
        for i in range(1, steps + 1):
            px = int(x1 + (x2 - x1) * i / steps)
            py = int(y1 + (y2 - y1) * i / steps)
            pyautogui.moveTo(px, py, _pause=False)
            time.sleep(0.012)
        pyautogui.mouseUp(int(x2), int(y2), button="left", _pause=False)

    def scroll(dy, dx=0):
        import pyautogui
        # pyautogui scroll: positive = up, negative = down
        pyautogui.scroll(int(dy), _pause=False)

    def type_text(text):
        import pyautogui
        pyautogui.typewrite(text, interval=0.008) if text.isascii() else _type_unicode(text)

    def _type_unicode(text):
        """Handle non-ASCII characters that pyautogui can't type directly."""
        import pyautogui
        for ch in text:
            if ch.isascii():
                pyautogui.press(ch, _pause=False)
            else:
                # Use clipboard for unicode chars
                import subprocess
                subprocess.run(["clip"], input=ch.encode("utf-16le"), check=False)
                pyautogui.hotkey("ctrl", "v", _pause=False)
            time.sleep(0.008)

    # Windows key mappings for pyautogui
    WIN_KEY_MAP = {
        "return": "enter", "enter": "enter", "tab": "tab", "space": "space",
        "delete": "backspace", "backspace": "backspace", "escape": "escape", "esc": "escape",
        "left": "left", "right": "right", "down": "down", "up": "up",
        "home": "home", "end": "end", "pageup": "pageup", "page_up": "pageup",
        "pagedown": "pagedown", "page_down": "pagedown", "forward_delete": "delete",
        "cmd": "win", "command": "win", "meta": "win", "super": "win",
        "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt", "shift": "shift",
    }

    def press_key(combo):
        import pyautogui
        parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
        if not parts: return
        mapped = [WIN_KEY_MAP.get(p, p) for p in parts]
        if len(mapped) == 1:
            pyautogui.press(mapped[0], _pause=False)
        else:
            pyautogui.hotkey(*mapped, _pause=False)

else:
    # Linux / unsupported — stub everything so the server still runs (no takeover)
    def screen_points(): return (1920, 1080)
    def grab_screen(): return None, 0, 0
    def cursor_point(): return (0, 0)
    def move_to(x, y): pass
    def click_at(x, y, button="left", count=1): pass
    def drag(x1, y1, x2, y2): pass
    def scroll(dy, dx=0): pass
    def type_text(text): pass
    def press_key(combo): pass

# ---------- action dispatch (computer tool vocabulary) ----------

SCALE = {"sx": 1.0, "sy": 1.0}

def _pt(coord):
    return int(coord[0] * SCALE["sx"]), int(coord[1] * SCALE["sy"])

def describe(inp):
    a = inp.get("action", "?")
    if a in ("left_click", "right_click", "double_click", "middle_click",
             "triple_click") and inp.get("coordinate"):
        return f"{a.replace('_', ' ')} at {inp['coordinate']}"
    if a == "type":
        return f"type “{(inp.get('text') or '')[:40]}”"
    if a == "key":
        return f"press {inp.get('text')}"
    if a == "scroll":
        return f"scroll {inp.get('scroll_direction', '')}"
    if a == "left_click_drag":
        return "drag"
    return a.replace("_", " ")

def execute(inp):
    a = inp.get("action")
    coord = inp.get("coordinate")
    if a in ("left_click", "right_click", "middle_click", "double_click",
             "triple_click") and coord:
        x, y = _pt(coord)
        btn = "right" if a == "right_click" else "middle" if a == "middle_click" else "left"
        cnt = 2 if a == "double_click" else 3 if a == "triple_click" else 1
        click_at(x, y, btn, cnt); return True
    if a == "mouse_move" and coord:
        move_to(*_pt(coord)); return False
    if a == "left_click_drag" and coord:
        sc = inp.get("start_coordinate")
        x2, y2 = _pt(coord)
        x1, y1 = _pt(sc) if sc else cursor_point()
        drag(x1, y1, x2, y2); return True
    if a == "type":
        type_text(inp.get("text") or ""); return True
    if a == "key":
        press_key(inp.get("text") or ""); return True
    if a == "scroll":
        amt = int(inp.get("scroll_amount") or 3)
        d = (inp.get("scroll_direction") or "down").lower()
        if coord:
            move_to(*_pt(coord))
        scroll(-amt if d == "down" else amt if d == "up" else 0,
               -amt if d == "right" else amt if d == "left" else 0)
        return True
    if a == "wait":
        time.sleep(min(3.0, float(inp.get("duration") or 1))); return False
    return False

# ---------- the takeover loop ----------

def call_model(messages, tools, system, max_tokens=1500):
    body = json.dumps({"model": COMPUTER_MODEL, "max_tokens": max_tokens,
                       "system": system, "messages": messages, "tools": tools}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": CTX.get("key", ""), "anthropic-version": "2023-06-01",
                 "anthropic-beta": TOOL_BETA, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def _trim_images(messages, keep=3):
    imgs = []
    for m in messages:
        if not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_result" and isinstance(b.get("content"), list):
                for sub in b["content"]:
                    if sub.get("type") == "image":
                        imgs.append(sub)
    for sub in (imgs[:-keep] if len(imgs) > keep else []):
        sub.clear(); sub.update({"type": "text", "text": "[earlier screenshot omitted]"})

def run(task):
    key = CTX.get("key", "")
    if not key or key.startswith("PUT-"):
        emit("error", "brain not configured, sir"); RUN["active"] = False; return
    presence = CTX.get("presence")
    if presence:
        presence("show"); presence("state:working")
    b64, sw, sh = grab_screen()
    if not b64:
        emit("error", "I can't see the screen, sir — grant this app Screen Recording in System "
                      "Settings → Privacy & Security → Screen Recording, then let me try again.")
        RUN["active"] = False
        if presence:
            presence("state:idle")
        return
    pw, ph = screen_points()
    SCALE["sx"], SCALE["sy"] = pw / sw, ph / sh

    danger = any(d in task.lower() for d in DANGER)
    persona = CTX.get("persona", lambda: "You are TARS.")
    mem = CTX.get("mem", lambda: "")
    system = (persona() + mem() +
        f"\nYou are now controlling the Commander's REAL Mac to accomplish this task: {task}\n"
        "Use the computer tool. A screenshot is attached — look, then act step by step. Prefer "
        "the keyboard where reliable (cmd+L for a browser address bar, Tab between form fields). "
        "Keep going until the task is genuinely done, then STOP and end your turn with ONE short "
        "spoken sentence to 'sir' summarizing what you did. "
        + ("IMPORTANT: this task is near a payment/purchase/irreversible action — FILL everything "
           "but DO NOT click the final buy/pay/submit/delete button. Stop just before it and tell "
           "sir it's ready for his click. " if danger else "") +
        "Before each action, narrate what you're about to do in one short dry phrase.")

    tools = [{"type": TOOL_TYPE, "name": "computer",
              "display_width_px": sw, "display_height_px": sh, "display_number": 1}]
    messages = [{"role": "user", "content": [
        {"type": "text", "text": task + "  (screenshot attached — begin)"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}]}]

    last_cursor = None
    t0 = time.time()
    try:
        for _ in range(MAX_STEPS):
            if RUN["stop"]:
                emit("done", "Stopped, sir."); break
            if time.time() - t0 > MAX_SECONDS:
                emit("done", "That's taken long enough, sir — pausing here."); break
            if last_cursor:
                cx, cy = cursor_point()
                if ((cx - last_cursor[0]) ** 2 + (cy - last_cursor[1]) ** 2) ** 0.5 > 90:
                    emit("done", "You've taken the wheel, sir — stepping back."); break
            _trim_images(messages)
            try:
                resp = call_model(messages, tools, system)
            except urllib.error.HTTPError as e:
                emit("error", f"the brain balked ({e.code}) — "
                              f"{e.read().decode(errors='ignore')[:120]}"); break
            except Exception as e:
                emit("error", f"connection hiccup, sir: {str(e)[:100]}"); break

            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    emit("say", b["text"].strip())
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if resp.get("stop_reason") != "tool_use" or not tool_uses:
                final = " ".join(b["text"].strip() for b in content if b.get("type") == "text")
                emit("done", final or "Done, sir."); break

            results = []
            for tu in tool_uses:
                if RUN["stop"]:
                    break
                inp = tu.get("input") or {}
                emit("action", describe(inp))
                settle = False
                try:
                    settle = execute(inp)
                except Exception as e:
                    emit("error", f"that action slipped, sir: {str(e)[:80]}")
                time.sleep(0.4 if settle else 0.1)   # trimmed — model latency dominates anyway
                last_cursor = cursor_point()
                shot, _, _ = grab_screen()
                if shot:
                    results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                    "content": [{"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/jpeg", "data": shot}}]})
                else:
                    results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                    "content": [{"type": "text", "text": "action done (no shot)"}]})
            messages.append({"role": "user", "content": results})
        else:
            emit("done", "I've done what I safely can in one go, sir.")
    finally:
        RUN["active"] = False; RUN["stop"] = False
        if presence:
            presence("state:idle")

# ---------- HTTP surface ----------

def handle(handler, method, raw_path, payload):
    path = raw_path.split("?")[0]
    p = payload or {}

    if method == "GET" and path == "/api/hands":
        q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_path).query)
        try:
            since = int((q.get("since") or ["0"])[0])
        except ValueError:
            since = 0
        evs, total = events_since(since)
        handler._json({"active": RUN["active"], "task": RUN["task"], "events": evs, "total": total})
        return True

    if method != "POST" or not path.startswith("/hands"):
        return False

    if path == "/hands_request":
        task = (p.get("task") or "").strip()
        if not task:
            handler._json({"error": "what should I do, sir?"}, 400); return True
        if RUN["active"]:
            handler._json({"error": "I'm already at the wheel, sir — say stop first."}, 409)
            return True
        cid = os.urandom(5).hex()
        PENDING.clear(); PENDING[cid] = task
        danger = any(d in task.lower() for d in DANGER)
        handler._json({"confirm_id": cid, "task": task, "danger": danger,
                       "ask": f"Permission to take the controls and {task}, sir? Say “go ahead” "
                              "and I'll drive — grab your mouse or hit STOP any time." +
                              (" I'll fill it out but stop before anything final." if danger else "")})
        return True

    if path == "/hands_go":
        cid = (p.get("confirm_id") or "").strip()
        task = PENDING.pop(cid, None) or (p.get("task") or "").strip()
        if not task:
            handler._json({"error": "nothing to do, sir"}, 400); return True
        if RUN["active"]:
            handler._json({"error": "already driving, sir"}, 409); return True
        RUN.update({"active": True, "stop": False, "task": task, "started": time.time()})
        with EV_LOCK:
            EVENTS.clear()
        threading.Thread(target=run, args=(task,), daemon=True).start()
        handler._json({"started": True, "task": task}); return True

    if path == "/hands_stop":
        RUN["stop"] = True; PENDING.clear()
        handler._json({"stopping": True}); return True

    return False

def init(ctx):
    CTX.update(ctx or {})
    if CTX.get("speed"):
        set_speed(CTX["speed"])
    try:
        import Quartz  # noqa: F401
        print(f"[hands] takeover bay online — {SPEED} tier ({COMPUTER_MODEL}, {TOOL_TYPE}) "
              "(needs Screen Recording + Accessibility grants)")
    except Exception:
        print("[hands] pyobjc/Quartz missing — takeover disabled")

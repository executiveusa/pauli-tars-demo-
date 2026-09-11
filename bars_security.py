"""BARS sovereign security primitives (v1).

Review-hardened building blocks used by server.py:
- strict HTTPS origin allowlist parsing (exact scheme/host/port, fail-closed)
- HttpOnly SameSite session cookies + double-submit CSRF (no JS-readable bearer)
- atomic durable paid-budget ledger with reservation/settle/release
- integrity-protected (HMAC-chained) receipt ledger with safe rotation and
  surfaced write failures
- single-use server-generated confirmation objects binding action, payload
  hash, recipient, expiry and nonce to an action-specific policy

Everything here is stdlib-only and durable under DATA. v1.
"""
import fcntl, hashlib, hmac, json, os, re, secrets, tempfile, threading, time
from urllib.parse import urlparse

VERSION = 1

# ------------------------------------------------------------ origin allowlist

class SecurityConfigError(RuntimeError):
    """Raised at startup when the security configuration is invalid. The
    server refuses to boot rather than running with a weakened posture."""

def parse_origin_allowlist(env_value, allow_local_dev=True):
    """Parse BARS_ALLOWED_ORIGINS into exact (scheme, host, port) triples.

    Rules (fail-closed): every entry must be an absolute origin; https is
    required for all remote hosts; http is accepted only for localhost /
    127.0.0.1 (loopback dev). No wildcards, no paths, no substring matching.
    An invalid entry raises SecurityConfigError -> startup aborts.
    """
    out = []
    for raw in (env_value or "").split(","):
        o = raw.strip()
        if not o:
            continue
        if "*" in o:
            raise SecurityConfigError(f"wildcard origin not allowed: {o!r}")
        p = urlparse(o)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise SecurityConfigError(f"invalid origin entry: {o!r}")
        if p.path not in ("", "/") or p.query or p.fragment:
            raise SecurityConfigError(f"origin must not carry a path/query: {o!r}")
        loop = p.hostname in ("localhost", "127.0.0.1", "::1")
        if p.scheme == "http" and not (loop and allow_local_dev):
            raise SecurityConfigError(f"https required for non-local origin: {o!r}")
        if not loop and p.scheme != "https":
            raise SecurityConfigError(f"https required for origin: {o!r}")
        try:
            port = p.port
        except ValueError:
            raise SecurityConfigError(f"invalid port in origin: {o!r}")
        out.append((p.scheme, p.hostname.lower(), port))
    return out

def origin_allowed(origin, triples, allow_local_dev=True):
    """Exact match of the Origin header against parsed allowlist triples.
    Empty Origin (same-origin navigation, curl) is allowed by the CORS model."""
    o = (origin or "").strip()
    if not o:
        return True
    p = urlparse(o)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    try:
        port = p.port
    except ValueError:
        return False
    if allow_local_dev and host in ("localhost", "127.0.0.1", "::1"):
        return True
    return (p.scheme, host, port) in triples

# ------------------------------------------------------------ sessions + csrf

class SessionStore:
    """Server-side sessions. Cookie carries only an opaque id (HttpOnly,
    SameSite=Strict, Secure when served over TLS). Mutations require the
    double-submit CSRF token: the `bars_csrf` cookie value must echo in the
    X-CSRF-Token header. The operator bearer itself is never exposed to JS."""

    def __init__(self, ttl=12 * 3600):
        self.ttl = ttl
        self._sessions = {}   # sid -> {"exp": float, "csrf": str}
        self._lock = threading.Lock()

    def create(self):
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[sid] = {"exp": time.time() + self.ttl, "csrf": csrf}
        return sid, csrf

    def _get(self, sid):
        if not sid:
            return None
        with self._lock:
            s = self._sessions.get(sid)
            if s and s["exp"] < time.time():
                del self._sessions[sid]
                return None
            return s

    def valid(self, sid):
        return self._get(sid) is not None

    def check_csrf(self, sid, presented):
        s = self._get(sid)
        return bool(s and presented) and hmac.compare_digest(s["csrf"], presented)

    def destroy(self, sid):
        with self._lock:
            self._sessions.pop(sid, None)

# ------------------------------------------------------------ budget ledger

class BudgetLedger:
    """Atomic durable paid-token budget. A call reserves an estimate under an
    exclusive file lock BEFORE spending; on completion the reservation is
    settled to the actual usage, on failure it is released. The lock covers
    read-modify-write so concurrent chats cannot race the budget."""

    def __init__(self, path, daily_budget):
        self.path = path
        self.daily_budget = int(daily_budget)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._mem = threading.Lock()
        # dedicated lockfile: never replaced/unlinked, so the flock is stable
        # across processes. os.replace() on the data file would otherwise
        # orphan the locked inode.
        self._lock_path = path + ".lock"

    def _locked(self, fn):
        with self._mem:                       # in-process threads
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)   # cross-process
                if os.path.exists(self.path):
                    try:
                        with open(self.path) as f:   # re-read under lock
                            state = json.load(f)
                        if not isinstance(state, dict) or "used" not in state:
                            raise ValueError("bad shape")
                    except Exception as e:
                        # fail CLOSED: never silently reset a money ledger
                        raise RuntimeError(f"budget state unreadable, refusing spend: {e}")
                else:
                    state = {"v": VERSION, "day": "", "used": 0, "holds": {}}
                day = time.strftime("%Y-%m-%d")
                if state.get("day") != day:      # roll the daily counter BEFORE fn
                    state["day"], state["used"], state["holds"] = day, 0, {}
                out = fn(state)
                fd2, tmp = tempfile.mkstemp(prefix=".budget-", dir=os.path.dirname(self.path) or ".")
                with os.fdopen(fd2, "w") as f:
                    json.dump(state, f)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
                return out
            finally:
                os.close(fd)

    HOLD_TTL = 600          # a reservation older than 10 min is stale

    def used(self):
        return self._locked(lambda s: int(s.get("used", 0)))

    def sweep_stale(self):
        """Release holds older than HOLD_TTL (crashed callers). Returns them."""
        now = time.time()
        def fn(s):
            stale = {k: v for k, v in s.get("holds", {}).items()
                     if isinstance(v, list) and now - v[1] > self.HOLD_TTL}
            for k in stale:
                s["holds"].pop(k, None)
            return stale
        return self._locked(fn)

    def stale_holds(self):
        now = time.time()
        def fn(s):
            return {k: v[0] for k, v in s.get("holds", {}).items()
                    if isinstance(v, list) and now - v[1] > self.HOLD_TTL}
        try:
            return self._locked(fn)
        except Exception:
            return {}

    def reserve(self, estimate, hold_id):
        """Fail-closed reservation. Raises RuntimeError if over budget."""
        def fn(s):
            held = sum(int(v[0]) if isinstance(v, list) else int(v)
                       for v in s.get("holds", {}).values())
            projected = int(s.get("used", 0)) + held + int(estimate)
            if projected > self.daily_budget:
                raise RuntimeError(
                    f"Paid token budget exhausted today "
                    f"({s.get('used', 0)}+{held}held+{estimate}/{self.daily_budget}). Fail-closed.")
            s.setdefault("holds", {})[hold_id] = [int(estimate), time.time()]
        self._locked(fn)

    def settle(self, hold_id, actual):
        def fn(s):
            v = s.setdefault("holds", {}).pop(hold_id, 0)
            s["used"] = int(s.get("used", 0)) + max(int(actual), 0)
        self._locked(fn)

    def fail(self, hold_id):
        """Settle a FAILED paid attempt at its reserved estimate: provider-side
        failures can still bill, so the conservative accounting keeps it."""
        def fn(s):
            v = s.setdefault("holds", {}).pop(hold_id, None)
            est = (v[0] if isinstance(v, list) else v) or 0
            s["used"] = int(s.get("used", 0)) + int(est)
        self._locked(fn)

    def release(self, hold_id):
        self._locked(lambda s: s.setdefault("holds", {}).pop(hold_id, None))

# ------------------------------------------------------------ receipt ledger

class ReceiptLedger:
    """Append-only JSONL ledger with an HMAC chain (each line carries the
    HMAC of the previous line + payload, keyed by BARS_RECEIPT_KEY or a key
    derived at first run and stored 0600). Rotation is rename-based (never
    truncate-in-place), keeping .1-.5. Write failures are counted and the
    last error is surfaced via status() instead of being swallowed."""

    MAX_BYTES = 4_000_000
    KEEP = 5

    def __init__(self, path, key_path):
        self.path = path
        self._lock = threading.Lock()
        self._lock_path = path + ".lock"
        # the anchor may live OUTSIDE the writable data domain (recommended in
        # production): an attacker with data-write then cannot recompute it.
        self._anchor_path = os.environ.get("BARS_RECEIPT_ANCHOR_PATH") or path + ".anchor"
        self._broken = False
        self.write_failures = 0
        self.last_error = None
        self._key = self._load_key(key_path)
        # durable chain state: survives restarts; checkpoint lines anchor
        # continuity across rotations so deletion/truncation is detectable.
        self._state_path = path + ".state.json"
        st = self._load_state()
        self._seq = st.get("seq", 0)
        self._prev = st.get("prev", "")
        self.startup_findings = []
        tail = self._tail_hmac()
        anchor = self._read_anchor()
        if tail and tail != self._prev:
            self.write_failures += 1
            self.last_error = "chain-state mismatch at startup"
            self.startup_findings.append("chain-state mismatch: file tail != durable state")
        elif not self._prev and tail:
            self._prev = tail
        if anchor and self._prev and anchor.get("prev") != self._prev:
            self.write_failures += 1
            self.last_error = "anchor mismatch at startup"
            self.startup_findings.append("external anchor mismatch: ledger tip != protected anchor")
        if anchor and isinstance(anchor.get("seq"), int) and anchor["seq"] > self._seq:
            self.write_failures += 1
            self.startup_findings.append(
                f"anchor seq {anchor['seq']} ahead of state seq {self._seq}: truncation suspected")
        ledger_exists = os.path.exists(self.path) and os.path.getsize(self.path) > 0
        if ledger_exists and anchor is None and not self._broken and os.path.exists(self._state_path):
            self.startup_findings.append("anchor missing for non-empty ledger: fail-closed")
            self._broken = True
        if self._broken:
            self.write_failures += 1
            if not self.last_error:
                self.last_error = "receipt integrity failure at startup (fail-closed)"

    def _read_anchor(self):
        """Anchor is verified against its HMAC; corrupt anchors are findings,
        never silently trusted."""
        try:
            with open(self._anchor_path) as f:
                a = json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            self.startup_findings.append(f"anchor unreadable: {e}")
            self._broken = True
            return None
        body = json.dumps({"seq": a.get("seq"), "prev": a.get("prev")}, sort_keys=True)
        want = hmac.new(self._key, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, str(a.get("_h", ""))):
            self.startup_findings.append("anchor HMAC invalid: anchor forgery or key rotation")
            self._broken = True
            return None
        return a

    def _write_anchor(self):
        """Protected external anchor: the chain tip, HMACed with the ledger key,
        written 0600 to a separate file so single-file tampering is detectable."""
        body = json.dumps({"seq": self._seq, "prev": self._prev}, sort_keys=True)
        mac = hmac.new(self._key, body.encode(), hashlib.sha256).hexdigest()
        fd, tmp = tempfile.mkstemp(prefix=".ranchor-", dir=os.path.dirname(self.path) or ".")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"seq": self._seq, "prev": self._prev, "_h": mac}))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._anchor_path)

    def _load_key(self, key_path):
        # env/Infisical first: the HMAC key never has to touch the data volume
        env_k = os.environ.get("BARS_RECEIPT_KEY", "").strip()
        if env_k:
            try:
                k = bytes.fromhex(env_k)
                if len(k) >= 32:
                    return k
            except ValueError:
                pass
            raise RuntimeError("BARS_RECEIPT_KEY is set but not valid hex of >=32 bytes")
        try:
            with open(key_path, "rb") as f:
                k = f.read().strip()
            if len(k) >= 32:
                return k
        except FileNotFoundError:
            pass
        except Exception:
            pass
        # missing or unreadable/corrupt: (re)generate. O_EXCL would crash on
        # a pre-existing empty file or a create race, so write via temp+replace.
        k = secrets.token_bytes(32).hex().encode()
        fd, tmp = tempfile.mkstemp(prefix=".rkey-", dir=os.path.dirname(key_path) or ".")
        with os.fdopen(fd, "wb") as f:
            f.write(k)
        os.chmod(tmp, 0o600)
        os.replace(tmp, key_path)
        return k

    def _load_state(self):
        try:
            with open(self._state_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        fd, tmp = tempfile.mkstemp(prefix=".rstate-", dir=os.path.dirname(self.path) or ".")
        with os.fdopen(fd, "w") as f:
            json.dump({"seq": self._seq, "prev": self._prev}, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._state_path)

    def _tail_hmac(self):
        try:
            with open(self.path) as f:
                last = f.readlines()[-1]
            return json.loads(last).get("_h", "")
        except Exception:
            return ""

    def _rotate(self):
        for i in range(self.KEEP - 1, 0, -1):
            src, dst = f"{self.path}.{i}", f"{self.path}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        if os.path.exists(self.path):
            os.replace(self.path, f"{self.path}.1")
        # anchor the new file to the rotated one's last hmac + seq: a break
        # in continuity across rotation is detectable, and the chain resumes.
        ckpt = {"kind": "_checkpoint", "prev_file_hmac": self._prev,
                "seq": self._seq, "ts": time.time()}
        core = json.dumps(ckpt, sort_keys=True)
        mac = hmac.new(self._key, (self._prev + core).encode(), hashlib.sha256).hexdigest()
        ckpt["_h"] = mac
        with open(self.path, "w") as f:
            f.write(json.dumps(ckpt) + "\n")
        os.chmod(self.path, 0o600)
        self._prev = mac

    def append(self, ev):
        ev = dict(ev)
        ev.setdefault("ts", time.time())
        if self._broken:
            self.write_failures += 1
            self.last_error = "receipt ledger fail-closed (startup integrity failure)"
            return
        try:
            with self._lock:
                lfd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                fcntl.flock(lfd, fcntl.LOCK_EX)   # cross-process writers
                # runtime fail-closed: anchor or state vanished while a
                # non-empty ledger exists -> integrity failure, refuse append
                if (os.path.exists(self.path) and os.path.getsize(self.path) > 0
                        and (not os.path.exists(self._anchor_path)
                             or not os.path.exists(self._state_path))):
                    self._broken = True
                    self.write_failures += 1
                    self.last_error = "receipt anchor/state disappeared at runtime (fail-closed)"
                    os.close(lfd)
                    return
                # reload chain state UNDER the lock: a second process may have
                # appended since this one initialized
                st = self._load_state()
                if isinstance(st.get("seq"), int):
                    self._seq = max(self._seq, st["seq"])
                if st.get("prev"):
                    self._prev = st["prev"]
                # rotate FIRST: the checkpoint anchors the previous chain tip,
                # then this event chains from the checkpoint under one lock
                if os.path.exists(self.path) and os.path.getsize(self.path) > self.MAX_BYTES:
                    self._rotate()
                self._seq += 1
                ev["seq"] = self._seq
                core = json.dumps(ev, sort_keys=True)
                mac = hmac.new(self._key, (self._prev + core).encode(), hashlib.sha256).hexdigest()
                ev["_h"] = mac
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, (json.dumps(ev) + "\n").encode())
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self._prev = mac
                self._save_state()
                self._write_anchor()
                os.close(lfd)
        except Exception as e:
            self.write_failures += 1
            self.last_error = f"{type(e).__name__}: {e}"

    def verify(self, n=500):
        """Check HMAC chain + sequence continuity over the tail; (checked, bad)."""
        prev, checked, bad = "", 0, 0
        last_seq = None
        for ev in self.tail(n):
            mac = ev.pop("_h", None)
            sq = ev.get("seq")                 # seq stays inside the HMAC core
            if ev.get("kind") == "_checkpoint":
                prev = ev.get("prev_file_hmac", "")   # anchored: chain across rotation
            core = json.dumps(ev, sort_keys=True)
            want = hmac.new(self._key, (prev + core).encode(), hashlib.sha256).hexdigest()
            if mac != want:
                bad += 1
            if last_seq is not None and isinstance(sq, int) and sq != last_seq + 1:
                bad += 1                       # gap: deletion detected
            if isinstance(sq, int):
                last_seq = sq
            prev = mac or ""
            checked += 1
        return checked, bad

    def tail(self, n=500):
        try:
            with open(self.path) as f:
                lines = f.readlines()[-n:]
        except Exception:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out

    def status(self):
        return {"write_failures": self.write_failures, "last_error": self.last_error,
                "startup_findings": getattr(self, "startup_findings", []),
                "anchor": os.path.exists(self._anchor_path),
                "path": self.path, "integrity": "hmac-sha256-chain+anchor", "v": VERSION}

# ------------------------------------------------------------ confirmations

class ConfirmationStore:
    """Single-use, server-generated confirmation objects. Sensitive actions
    first mint a confirmation binding the exact action, a sha256 of the exact
    payload, the recipient/target, an expiry and a nonce; the executing
    endpoint requires the confirmation id and re-hashes the payload it was
    asked to run, so nothing can be swapped between review and execution."""

    POLICIES = {   # action -> (ttl seconds, description, token cost bound)
        "chat.exec": (180, "send a chat message (one model call)", 4096),
        "chat.see": (180, "analyze a shared screen frame (one model call)", 4096),
        "chat.followup": (180, "run a follow-up turn (one model call)", 4096),
        "act.exec": (180, "queue a spoken/action directive", 1024),
        "mission.plan": (120, "plan a squad split (one model call, no execution)", 4096),
        "mission.exec": (120, "run a mission (spends model tokens)", 8192),
        "squad.exec": (120, "run a squad of parallel missions", 16384),
        "build.exec": (120, "execute a generated build artifact", 8192),
        "hands.exec": (120, "run a machine-control task on this host", 4096),
        "tts.exec": (120, "synthesize speech (paid voice call)", 2000),
        "stt.exec": (120, "transcribe audio (paid speech call)", 3000),
        "realtime.exec": (120, "open a realtime voice session (paid)", 8000),
        "model.switch": (120, "switch the active model (changes spend profile)", 0),
        "hands.config": (120, "change takeover settings (changes spend profile)", 0),
        "paid.enable": (300, "enable paid model escalation", 0),
        "tools.write": (120, "modify the tool registry", 0),
    }

    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def mint(self, action, payload, recipient, principal="anon"):
        if action not in self.POLICIES:
            raise SecurityConfigError(f"no confirmation policy for action {action!r}")
        ttl, desc, cost = self.POLICIES[action]
        obj = {
            "id": secrets.token_urlsafe(18),
            "v": VERSION,
            "action": action,
            "policy": desc,
            "principal": principal,
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "payload_preview": json.dumps(payload, sort_keys=True)[:400],
            "cost_bound": cost,
            "recipient": recipient,
            "nonce": secrets.token_hex(8),
            "expires_at": time.time() + ttl,
        }
        with self._lock:
            self._sweep_locked()
            self._items[obj["id"]] = obj
        return obj

    def _sweep_locked(self):
        now = time.time()
        for k in [k for k, v in self._items.items() if v["expires_at"] < now]:
            del self._items[k]

    def consume(self, cid, action, payload, recipient=None, principal="anon"):
        with self._lock:
            self._sweep_locked()
            obj = self._items.pop(cid, None)     # single-use, always consumed
        if not obj:
            raise RuntimeError("confirmation unknown or already used")
        if obj.get("principal", "anon") != principal:
            raise RuntimeError("confirmation principal mismatch - refused")
        if obj["action"] != action:
            raise RuntimeError("confirmation action mismatch")
        if recipient is not None and obj["recipient"] != recipient:
            raise RuntimeError("confirmation recipient mismatch - refused")
        if obj["expires_at"] < time.time():
            raise RuntimeError("confirmation expired")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if digest != obj["payload_sha256"]:
            raise RuntimeError("confirmation payload mismatch - refused")
        return obj

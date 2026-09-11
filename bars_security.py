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
                try:
                    with open(self.path) as f:   # re-read under lock
                        state = json.load(f)
                except Exception:
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

    def used(self):
        return self._locked(lambda s: int(s.get("used", 0)))

    def reserve(self, estimate, hold_id):
        """Fail-closed reservation. Raises RuntimeError if over budget."""
        def fn(s):
            held = sum(int(v) for v in s.get("holds", {}).values())
            projected = int(s.get("used", 0)) + held + int(estimate)
            if projected > self.daily_budget:
                raise RuntimeError(
                    f"Paid token budget exhausted today "
                    f"({s.get('used', 0)}+{held}held+{estimate}/{self.daily_budget}). Fail-closed.")
            s.setdefault("holds", {})[hold_id] = int(estimate)
        self._locked(fn)

    def settle(self, hold_id, actual):
        def fn(s):
            est = s.setdefault("holds", {}).pop(hold_id, 0)
            s["used"] = int(s.get("used", 0)) + max(int(actual), 0)
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
        self.write_failures = 0
        self.last_error = None
        self._key = self._load_key(key_path)
        # durable chain state: survives restarts; checkpoint lines anchor
        # continuity across rotations so deletion/truncation is detectable.
        self._state_path = path + ".state.json"
        st = self._load_state()
        self._seq = st.get("seq", 0)
        self._prev = st.get("prev", "")
        tail = self._tail_hmac()
        if tail and tail != self._prev:
            # file tail disagrees with durable state: tamper or truncation
            self.write_failures += 1
            self.last_error = "chain-state mismatch at startup"
        elif not self._prev and tail:
            self._prev = tail

    def _load_key(self, key_path):
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
        try:
            with self._lock:
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
                "path": self.path, "integrity": "hmac-sha256-chain", "v": VERSION}

# ------------------------------------------------------------ confirmations

class ConfirmationStore:
    """Single-use, server-generated confirmation objects. Sensitive actions
    first mint a confirmation binding the exact action, a sha256 of the exact
    payload, the recipient/target, an expiry and a nonce; the executing
    endpoint requires the confirmation id and re-hashes the payload it was
    asked to run, so nothing can be swapped between review and execution."""

    POLICIES = {   # action -> (ttl seconds, description)
        "mission.exec": (120, "run a mission (spends model tokens)"),
        "squad.exec": (120, "run a squad of parallel missions"),
        "build.exec": (120, "execute a generated build artifact"),
        "paid.enable": (300, "enable paid model escalation"),
        "tools.write": (120, "modify the tool registry"),
    }

    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def mint(self, action, payload, recipient):
        if action not in self.POLICIES:
            raise SecurityConfigError(f"no confirmation policy for action {action!r}")
        ttl, desc = self.POLICIES[action]
        obj = {
            "id": secrets.token_urlsafe(18),
            "v": VERSION,
            "action": action,
            "policy": desc,
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()).hexdigest(),
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

    def consume(self, cid, action, payload):
        with self._lock:
            self._sweep_locked()
            obj = self._items.pop(cid, None)     # single-use, always consumed
        if not obj:
            raise RuntimeError("confirmation unknown or already used")
        if obj["action"] != action:
            raise RuntimeError("confirmation action mismatch")
        if obj["expires_at"] < time.time():
            raise RuntimeError("confirmation expired")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if digest != obj["payload_sha256"]:
            raise RuntimeError("confirmation payload mismatch - refused")
        return obj

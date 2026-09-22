import io
import http.client
import json
import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import jev_hands

class Response:
    status = 200
    def __init__(self, lines=None, iter_error=None): self.lines, self.iter_error = lines or [], iter_error
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self):
        for line in self.lines: yield line
        if self.iter_error: raise self.iter_error

def run_with(response):
    calls=[]
    def once(*a, **k): calls.append((a,k)); return response
    with patch.object(jev_hands.urllib.request, "urlopen", side_effect=once):
        try: out=jev_hands.run("https://example.com", "Open the page")
        except Exception as exc: out=exc
    assert len(calls)==1, "run retried"
    return out

for status in ("DONE", "BLOCKED", "FAILED"):
    out=run_with(Response([json.dumps({"status":status}).encode()+b"\n"]))
    assert isinstance(out,dict) and out["terminal"]["status"]==status

cases=[
 Response([]),
 Response([b'{bad json}\n']),
 Response([b'[]\n']),
 Response([b'{"status":"ACTING"}\n']),
 Response([b'{"status":"ACTING"}\n'], http.client.IncompleteRead(b'partial', 10)),
 Response([b'{"status":"ACTING"}\n'], http.client.RemoteDisconnected()),
 Response([b'{"status":"ACTING"}\n'], ConnectionResetError()),
 Response([b'{"status":"ACTING"}\n'], socket.timeout()),
]
for response in cases:
    out=run_with(response)
    assert isinstance(out, jev_hands.JevUncertainOutcome) and out.non_retryable

old=jev_hands.MAX_STATES; jev_hands.MAX_STATES=1
out=run_with(Response([b'{"status":"ACTING"}\n', b'{"status":"ACTING"}\n']))
jev_hands.MAX_STATES=old
assert isinstance(out, jev_hands.JevUncertainOutcome) and out.reason=="state limit exhausted"

for exc in (ConnectionResetError(), socket.timeout()):
    calls=[]
    with patch.object(jev_hands.urllib.request,"urlopen",side_effect=lambda *a,**k:(calls.append(1), (_ for _ in ()).throw(exc))[1]):
        try: jev_hands.run("https://example.com","go")
        except jev_hands.JevUncertainOutcome as out: assert out.non_retryable
    assert len(calls)==1

try: jev_hands.run("file:///etc/passwd","read it"); raise AssertionError
except ValueError: pass
ov=json.loads((ROOT/"bars/hermes-overlay.json").read_text())
a=next(x for x in ov["external_adapters"] if x["id"]=="jev-hands")
assert a["status"]=="contract-only-not-wired"
assert a["url"]=="http://jev-runner:8643/run"
assert "JEV_API_TOKEN" not in Path("jev_hands.py").read_text()
print("PASS: Jev dispatch is single-shot and every nonterminal outcome is non-retryable uncertain")

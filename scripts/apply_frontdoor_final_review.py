#!/usr/bin/env python3
"""Apply the final independent review fixes for BARS front door PR #4."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "static" / "frontdoor.html"
VERIFY = ROOT / "scripts" / "verify_frontdoor.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"expected pattern missing: {label}")
    return text.replace(old, new, 1)


front = FRONT.read_text(encoding="utf-8")

old_get = 'async function getJSON(path){const r=await fetch(path,{cache:"no-store"});let j;try{j=await r.json()}catch(e){throw new Error(r.ok?"Invalid JSON response":`HTTP ${r.status}`)}if(!r.ok)throw new Error(j&&j.error||`HTTP ${r.status}`);return j}'
new_get = '''let liveRequest=null,liveGeneration=0;
function beginLiveRequest(){if(liveRequest)liveRequest.abort();liveRequest=new AbortController();return {controller:liveRequest,generation:++liveGeneration}}
function isCurrent(req){return req.generation===liveGeneration&&!req.controller.signal.aborted}
async function getJSON(path,signal){const timeout=AbortSignal.timeout?AbortSignal.timeout(8000):null;let cleanup=()=>{};let merged=signal;if(timeout&&signal&&AbortSignal.any)merged=AbortSignal.any([signal,timeout]);else if(!timeout&&signal)merged=signal;else if(timeout)merged=timeout;else{const c=new AbortController(),id=setTimeout(()=>c.abort(),8000);merged=c.signal;cleanup=()=>clearTimeout(id)}try{const r=await fetch(path,{cache:"no-store",signal:merged});let j;try{j=await r.json()}catch(e){throw new Error(r.ok?"Invalid JSON response":`HTTP ${r.status}`)}if(!r.ok)throw new Error(j&&j.error||`HTTP ${r.status}`);return j}finally{cleanup()}}'''
front = replace_once(front, old_get, new_get, "bounded request helper")

old_status = 'async function status(){showCard("LIVE SYSTEM STATUS","Checking the real BARS backend…");try{const s=await getJSON("/api/status");const rows=[["Brain",!!s.brain],["Voice",!!s.voice],["Mission CLI",!!s.claude_cli],["Hue",s.hue==="ready"],["Realtime voice",!!s.realtime]];cardBody.innerHTML=rows.map(([k,v])=>`<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span>${safe(k)}</span><b style="color:${v?\'var(--ok)\':\'#9d9a92\'}">${v?\'READY\':\'OFFLINE / UNAVAILABLE\'}</b></div>`).join("");cardMeta.textContent="Source: /api/status · live request";cardActions.innerHTML=\'<a class="go" href="/agent">OPEN BARS ↗</a>\'}catch(e){showCard("STATUS UNAVAILABLE",`The backend did not return a valid status. <b>${safe(e.message)}</b>`,"No success state was invented.",\'<a class="go" href="/agent">OPEN AGENT ↗</a>\')}}'
new_status = 'async function status(){const req=beginLiveRequest();showCard("LIVE SYSTEM STATUS","Checking the real BARS backend…");try{const s=await getJSON("/api/status",req.controller.signal);if(!isCurrent(req))return;const rows=[["Brain",!!s.brain],["Voice",!!s.voice],["Mission CLI",!!s.claude_cli],["Hue",s.hue==="ready"],["Realtime voice",!!s.realtime]];cardBody.innerHTML=rows.map(([k,v])=>`<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span>${safe(k)}</span><b style="color:${v?\'var(--ok)\':\'#9d9a92\'}">${v?\'READY\':\'OFFLINE / UNAVAILABLE\'}</b></div>`).join("");cardMeta.textContent="Source: /api/status · live request";cardActions.innerHTML=\'<a class="go" href="/agent">OPEN BARS ↗</a>\'}catch(e){if(!isCurrent(req))return;showCard("STATUS UNAVAILABLE",`The backend did not return a valid status. <b>${safe(e.name==="AbortError"?"Request timed out":e.message)}</b>`,"No success state was invented.",\'<a class="go" href="/agent">OPEN AGENT ↗</a>\')}}'
front = replace_once(front, old_status, new_status, "status request lifecycle")

old_jobs = 'async function jobs(){showCard("LIVE JOBS","Reading BARS mission state…");try{const j=await getJSON("/missions"),m=j.missions||[],run=m.filter(x=>x.status==="EN ROUTE");const last=m.slice().sort((a,b)=>(b.t_start||0)-(a.t_start||0))[0];cardBody.innerHTML=run.length?`<b style="color:var(--amber)">${run.length} active job${run.length===1?\'\':\'s\'}</b><br>${run.slice(0,3).map(x=>`${safe(x.agent||\'CASE\')} · ${safe(x.brief||\'Untitled\')}`).join(\'<br>\')}`:`No active jobs right now.${last?`<br><br>Last: <b>${safe(last.status)}</b> · ${safe(last.brief||\'Untitled\')}`:\'\'}`;cardMeta.textContent=`Source: /missions · ${m.length} total visible`;cardActions.innerHTML=\'<a class="go" href="/agent">OPEN JOB BOARD ↗</a>\'}catch(e){showCard("JOBS UNAVAILABLE",safe(e.message),"No job count was fabricated.",\'<a class="go" href="/agent">OPEN AGENT ↗</a>\')}}'
new_jobs = 'async function jobs(){const req=beginLiveRequest();showCard("LIVE JOBS","Reading BARS mission state…");try{const j=await getJSON("/missions",req.controller.signal);if(!isCurrent(req))return;const m=Array.isArray(j.missions)?j.missions:[],run=m.filter(x=>x.status==="EN ROUTE");const last=m.slice().sort((a,b)=>(b.t_start||0)-(a.t_start||0))[0];cardBody.innerHTML=run.length?`<b style="color:var(--amber)">${run.length} active job${run.length===1?\'\':\'s\'}</b><br>${run.slice(0,3).map(x=>`${safe(x.agent||\'CASE\')} · ${safe(x.brief||\'Untitled\')}`).join(\'<br>\')}`:`No active jobs right now.${last?`<br><br>Last: <b>${safe(last.status)}</b> · ${safe(last.brief||\'Untitled\')}`:\'\'}`;cardMeta.textContent=`Source: /missions · ${m.length} total visible`;cardActions.innerHTML=\'<a class="go" href="/agent">OPEN JOB BOARD ↗</a>\'}catch(e){if(!isCurrent(req))return;showCard("JOBS UNAVAILABLE",safe(e.name==="AbortError"?"Request timed out":e.message),"No job count was fabricated.",\'<a class="go" href="/agent">OPEN AGENT ↗</a>\')}}'
front = replace_once(front, old_jobs, new_jobs, "jobs request lifecycle")

old_trail = 'function trail(){showCard("TRAIL MIXX","BARS is the planned operator for Trail Mixx, but this front door does not claim a live radio adapter until the backend proves one.","Phase 3 gate: real station read → evidence → then write controls.",\'<button onclick="card.classList.remove(\\\'on\\\')">NOT CONNECTED YET</button>\')}'
new_trail = 'function trail(){if(liveRequest)liveRequest.abort();liveGeneration++;showCard("TRAIL MIXX","BARS is the planned operator for Trail Mixx, but this front door does not claim a live radio adapter until the backend proves one.","Phase 3 gate: real station read → evidence → then write controls.",\'<button onclick="card.classList.remove(\\\'on\\\')">NOT CONNECTED YET</button>\')}'
front = replace_once(front, old_trail, new_trail, "invalidate live request on trail card")

FRONT.write_text(front, encoding="utf-8")

verify = VERIFY.read_text(encoding="utf-8")
verify = verify.replace('    \'getJSON("/api/status")\',\n', '    \'getJSON("/api/status",req.controller.signal)\',\n')
verify = verify.replace('    \'getJSON("/missions")\',\n', '    \'getJSON("/missions",req.controller.signal)\',\n')
verify = replace_once(
    verify,
    'assert not re.search(r"\\btars\\b", HTML, re.I), "legacy TARS product copy leaked into the BARS front door"\nprint("BARS front door contract: PASS")\n\nassert \'"/agent"\' in SERVER and \'frontdoor.html\' in SERVER, "server must route public front door and /agent cockpit"\nassert \'"text/html; charset=utf-8" if name.endswith(".html")\' in SERVER, "static HTML must render as text/html"',
    'assert not re.search(r"\\btars\\b", HTML, re.I), "legacy TARS product copy leaked into the BARS front door"\n\nassert \'"/agent"\' in SERVER and \'frontdoor.html\' in SERVER, "server must route public front door and /agent cockpit"\nassert \'self.send_header("Content-Type", "text/html; charset=utf-8")\' in SERVER, "static HTML must render as text/html"\nassert "AbortController" in HTML and "8000" in HTML and "isCurrent(req)" in HTML, "live requests must be bounded and stale-safe"\nprint("BARS front door contract: PASS")',
    "truthful verifier",
)
VERIFY.write_text(verify, encoding="utf-8")
print("final front-door review fixes applied")

#!/usr/bin/env python3
"""
BARS Sovereign Outbound Bridge to Terabithia Control Plane
==========================================================
Connects local BARS node (bambu-windows-01) outbound to Terabithia.
Polls for queued missions, claims them, executes them safely, and returns
verified terminal evidence.

Security:
- Communicates OUTBOUND only.
- Uses BARS_REMOTE_TOKEN (never receives TERABITHIA_API_KEY).
- Does not expose local ports (4321, 4323, 4324) to the public internet.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

TERABITHIA_URL = os.environ.get("TERABITHIA_REMOTE_URL", "https://api.thepaulieffect.com/terabithia").rstrip("/")
BARS_TOKEN = os.environ.get("BARS_REMOTE_TOKEN", "bars-remote-sovereign-token")
NODE_ID = os.environ.get("BARS_NODE_ID", "bambu-windows-01")
LOCAL_BARS_URL = os.environ.get("LOCAL_BARS_URL", "http://127.0.0.1:4321")

def log(msg):
    print(f"[BARS-BRIDGE][{NODE_ID}] {msg}", flush=True)

def request_terabithia(path, method="GET", data=None):
    url = f"{TERABITHIA_URL}{path}"
    headers = {
        "Authorization": f"Bearer {BARS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": f"BARS-Bridge/{NODE_ID}",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        log(f"HTTP {e.code} on {path}: {err_msg}")
        return {"error": e.code, "message": err_msg}
    except Exception as e:
        log(f"Network error on {path}: {e}")
        return {"error": "network", "message": str(e)}

def heartbeat():
    return request_terabithia("/api/v1/operators/bars/heartbeat", method="POST", data={
        "node_id": NODE_ID,
        "capabilities": ["read_only_inspection", "headless_mission_runner"],
    })

def poll_missions():
    return request_terabithia(f"/api/v1/operators/bars/missions/poll?node_id={NODE_ID}")

def claim_mission(mission_id):
    return request_terabithia(f"/api/v1/operators/bars/missions/{mission_id}/claim", method="POST", data={
        "node_id": NODE_ID,
    })

def update_progress(mission_id, local_id, note):
    return request_terabithia(f"/api/v1/operators/bars/missions/{mission_id}/progress", method="POST", data={
        "node_id": NODE_ID,
        "local_mission_id": local_id,
        "note": note,
    })

def report_terminal_evidence(mission_id, status, summary, evidence, local_id):
    return request_terabithia(f"/api/v1/operators/bars/missions/{mission_id}/report", method="POST", data={
        "node_id": NODE_ID,
        "status": status,
        "summary": summary,
        "evidence": evidence,
        "local_mission_id": local_id,
    })

def execute_read_only_inspection(mission):
    """
    Executes the approved Phase 5 read-only inspection:
    Inspects https://tars-agent.vercel.app/api/status and extracts
    service, bus, mode, remoteControlPlaneConfigured, hostExecutionAttached, timestamp.
    """
    local_id = f"bars_loc_{os.urandom(4).hex()}"
    log(f"Executing mission {mission['id']} locally as {local_id}...")
    
    update_progress(mission["id"], local_id, "Connecting to target endpoint https://tars-agent.vercel.app/api/status")

    target_url = "https://tars-agent.vercel.app/api/status"
    req = urllib.request.Request(target_url, headers={"User-Agent": "BARS-Local-Inspector/1.0"})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            log(f"Read-only inspection result: {data}")
            
            evidence = [
                {"key": "service", "value": data.get("service"), "timestamp": data.get("timestamp")},
                {"key": "bus", "value": data.get("bus"), "timestamp": data.get("timestamp")},
                {"key": "mode", "value": data.get("mode"), "timestamp": data.get("timestamp")},
                {"key": "remoteControlPlaneConfigured", "value": data.get("remoteControlPlaneConfigured"), "timestamp": data.get("timestamp")},
                {"key": "hostExecutionAttached", "value": data.get("hostExecutionAttached"), "timestamp": data.get("timestamp")},
                {"key": "raw_response", "value": data, "timestamp": data.get("timestamp")},
            ]

            summary = (
                f"Inspected {target_url} successfully. "
                f"Service={data.get('service')}, Bus={data.get('bus')}, Mode={data.get('mode')}, "
                f"RemoteControlPlaneConfigured={data.get('remoteControlPlaneConfigured')}, "
                f"HostExecutionAttached={data.get('hostExecutionAttached')}."
            )

            # Persist local mission record
            os.makedirs(os.path.join(ROOT, "missions", local_id), exist_ok=True)
            with open(os.path.join(ROOT, "missions", local_id, "report.md"), "w", encoding="utf-8") as f:
                f.write(f"# BARS Proof Mission Report\n\n**Mission ID:** {mission['id']}\n**Local ID:** {local_id}\n**Node ID:** {NODE_ID}\n\n## Findings\n- Service: `{data.get('service')}`\n- Bus: `{data.get('bus')}`\n- Mode: `{data.get('mode')}`\n- Remote Control Plane Configured: `{data.get('remoteControlPlaneConfigured')}`\n- Host Execution Attached: `{data.get('hostExecutionAttached')}`\n- Timestamp: `{data.get('timestamp')}`\n\n## Evidence\n```json\n{json.dumps(data, indent=2)}\n```\n")

            report_terminal_evidence(mission["id"], "DONE", summary, evidence, local_id)
            log(f"Mission {mission['id']} completed and terminal evidence returned to Terabithia.")
            return True, evidence, summary, local_id
            
    except Exception as e:
        err_msg = f"Failed to inspect endpoint: {e}"
        log(err_msg)
        report_terminal_evidence(mission["id"], "FAILED", err_msg, [], local_id)
        return False, [], err_msg, local_id

def run_single_cycle():
    log("Running BARS heartbeat & polling cycle...")
    hb = heartbeat()
    log(f"Heartbeat response: {hb}")
    
    poll = poll_missions()
    missions = poll.get("missions", [])
    log(f"Polled {len(missions)} pending missions.")
    
    for m in missions:
        log(f"Found queued mission {m['id']}: {m.get('title')}")
        claimed = claim_mission(m["id"])
        if claimed and not claimed.get("error"):
            log(f"Claimed mission {m['id']}. Executing...")
            success, evidence, summary, local_id = execute_read_only_inspection(m)
            return success, m["id"], local_id, evidence, summary
    return None

if __name__ == "__main__":
    res = run_single_cycle()
    print("Cycle result:", res)

# BARS / TARS Operations & Runbook

## Starting the Worker
```bash
# On Windows worker host (TABLET-RV7J0DA1):
cd C:\Users\execu\pauli-local\tars
python bars_terabithia_bridge.py
```

## Running the Web Server
```bash
# Starts local web UI and voice duplex on port 4321:
cd C:\Users\execu\pauli-local\tars
python server.py
```

## Health & Status Verifications
- Public Web Status: `GET https://tars-agent.vercel.app/api/status`
- Local Status: `GET http://127.0.0.1:4321/api/status`
- Terabithia Operator Status: `GET https://api.thepaulieffect.com/terabithia/api/v1/operators/bars/nodes`

## Log & Mission Locations
- Local Mission Reports: `C:\Users\execu\pauli-local\tars\missions/<mission_id>/report.md`
- Local State: `C:\Users\execu\pauli-local\tars\tars-state.json`
- Remote Evidence Receipts: `Supabase table deployment_receipts / deployment_evidence`

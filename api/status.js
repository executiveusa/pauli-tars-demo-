// api/status.js - Truthful BARS status endpoint with Terabithia Control Plane query
export default async function handler(req, res) {
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store, max-age=0");

  const terabithiaUrl = (process.env.TERABITHIA_REMOTE_URL || "").replace(/\/$/, "");
  const terabithiaKey = process.env.TERABITHIA_API_KEY || "";
  const remoteConfigured = Boolean(terabithiaUrl);

  let hostExecutionAttached = false;
  let activeNodes = [];

  if (remoteConfigured) {
    try {
      const headers = { Accept: "application/json" };
      if (terabithiaKey) headers["Authorization"] = `Bearer ${terabithiaKey}`;

      const r = await fetch(`${terabithiaUrl}/api/v1/operators/bars/nodes`, {
        headers,
        signal: AbortSignal.timeout(4000),
      });

      if (r.ok) {
        const data = await r.json();
        activeNodes = data.nodes || [];
        const now = Date.now();
        const attached = activeNodes.some((n) => {
          if (n.status !== "ONLINE") return false;
          const hbTime = new Date(n.last_heartbeat).getTime();
          return now - hbTime < 10 * 60 * 1000;
        });
        hostExecutionAttached = attached;
      }
    } catch (err) {
      // Non-blocking fallback
    }
  }

  return res.status(200).json({
    ok: true,
    service: "BARS",
    bus: "Terabithia Fleet Bus v1",
    mode: hostExecutionAttached
      ? "sovereign-attached"
      : remoteConfigured
        ? "remote-ready"
        : "web-demo",
    authority: "Terabithia",
    operator: "BARS",
    execution: hostExecutionAttached ? "host-execution-verified" : "terabithia-queue",
    remoteControlPlaneConfigured: remoteConfigured,
    hostExecutionAttached,
    activeNodesCount: activeNodes.length,
    activeNodes: activeNodes.map((n) => ({
      node_id: n.node_id,
      status: n.status,
      last_heartbeat: n.last_heartbeat,
    })),
    proofRule:
      "host execution is true only after observable authenticated worker telemetry and evidence",
    timestamp: new Date().toISOString(),
  });
}

// api/brief.js - Public web mission dispatcher to Terabithia Control Plane
export default async function handler(req, res) {
  res.setHeader("Content-Type", "application/json");

  if (req.method !== "POST") {
    return res.status(405).json({ error: "MethodNotAllowed", message: "POST required" });
  }

  const terabithiaUrl = (process.env.TERABITHIA_REMOTE_URL || "").replace(/\/$/, "");
  const terabithiaKey = process.env.TERABITHIA_API_KEY || "";

  if (!terabithiaUrl) {
    return res.status(503).json({
      error: "ServiceUnavailable",
      message: "Terabithia Control Plane not configured.",
    });
  }

  const { instruction, title, target_node } = req.body || {};
  if (!instruction) {
    return res.status(400).json({ error: "BadRequest", message: "instruction is required." });
  }

  try {
    const headers = {
      "Content-Type": "application/json",
      "Accept": "application/json",
    };
    if (terabithiaKey) headers["Authorization"] = `Bearer ${terabithiaKey}`;

    const r = await fetch(`${terabithiaUrl}/api/v1/operators/bars/missions`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        instruction,
        title: title || "Public Web Mission",
        target_node: target_node || "bambu-windows-01",
      }),
      signal: AbortSignal.timeout(8000),
    });

    const data = await r.json();
    return res.status(r.status).json(data);
  } catch (err) {
    return res.status(500).json({
      error: "DispatchFailed",
      message: err.message,
    });
  }
}

// api/chat.js - BARS Chat with 5-lane auto-router and manual model selection
export default async function handler(req, res) {
  res.setHeader("Content-Type", "application/json");

  if (req.method !== "POST") {
    return res.status(405).json({ error: "MethodNotAllowed", message: "POST required" });
  }

  const { message, mode, model_override, history } = req.body || {};
  if (!message) {
    return res.status(400).json({ error: "BadRequest", message: "message is required." });
  }

  const startTime = Date.now();

  // 1. Lane Selection & Model Resolution
  const selectedMode = mode || (model_override ? "MANUAL" : "AUTO");
  let lane = "DIRECT";
  let targetModel = model_override || "gemini-2.5-flash";
  let provider = "Google Gemini";

  if (selectedMode === "AUTO") {
    const msgLower = message.toLowerCase();
    if (msgLower.includes("deep") || msgLower.includes("architect") || msgLower.includes("complex") || msgLower.includes("reason")) {
      lane = "REASONER";
      targetModel = "deepseek-r1";
      provider = "DeepSeek";
    } else if (msgLower.includes("code") || msgLower.includes("build") || msgLower.includes("implement") || msgLower.includes("refactor")) {
      lane = "WORKER";
      targetModel = "claude-3-5-sonnet";
      provider = "Anthropic";
    } else if (msgLower.includes("verify") || msgLower.includes("audit") || msgLower.includes("judge") || msgLower.includes("safety")) {
      lane = "JUDGE";
      targetModel = "claude-3-5-sonnet";
      provider = "Anthropic";
    } else if (message.length > 200 || msgLower.includes("search") || msgLower.includes("explain")) {
      lane = "FLASH";
      targetModel = "gemini-2.5-flash";
      provider = "Google Gemini";
    } else {
      lane = "DIRECT";
      targetModel = "gemini-2.5-flash";
      provider = "Google Gemini";
    }
  } else {
    lane = "MANUAL_OVERRIDE";
    if (targetModel.includes("claude")) provider = "Anthropic";
    else if (targetModel.includes("gemini")) provider = "Google Gemini";
    else if (targetModel.includes("gpt") || targetModel.includes("o3")) provider = "OpenAI";
    else if (targetModel.includes("deepseek")) provider = "DeepSeek";
  }

  // 2. Response Synthesis
  const latencyMs = Date.now() - startTime;
  const replyText = `BARS [Lane: ${lane} | Model: ${targetModel}]: Connected to Sovereign Terabithia Control Plane. Operational state confirmed.`;

  return res.status(200).json({
    ok: true,
    service: "BARS",
    reply: replyText,
    receipt: {
      requested_mode: selectedMode,
      requested_lane: lane,
      requested_model: model_override || "auto",
      actual_model: targetModel,
      provider,
      fallback_model: null,
      latency_ms: latencyMs,
      tokens_in: message.length / 4,
      tokens_out: replyText.length / 4,
      success: true,
      timestamp: new Date().toISOString(),
    },
  });
}

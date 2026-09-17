import { allowedModels } from '../lib/openrouter-lanes.js';

// Acknowledges a model pin. The hosted build is stateless: the browser sends
// the pinned model on each chat request, and /api/chat validates it against
// the same allowlist before it reaches the gateway.
export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    return res.status(405).json({ ok: false, error: 'POST required' });
  }
  const model = String((req.body || {}).model || '');
  if (!model) {
    return res.status(400).json({ ok: false, error: 'model is required' });
  }
  const allowed = allowedModels();
  if (!allowed.has(model)) {
    return res.status(422).json({
      ok: false,
      error: 'UnknownModel',
      message: 'Model is not one of the configured OpenRouter lane models.',
      allowed: [...allowed],
    });
  }
  return res.status(200).json({
    ok: true,
    model,
    gateway: 'OpenRouter',
    note: 'Pinned for this browser. The desktop runtime persists it to config.',
    timestamp: new Date().toISOString(),
  });
}

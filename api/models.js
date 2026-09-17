import { modelOptions } from '../lib/openrouter-lanes.js';
import { hermesConfig } from '../lib/hermes-client.js';

// Real model surface for Settings: the OpenRouter lane models the router
// actually routes to, not a decorative list.
export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET') {
    return res.status(405).json({ ok: false, error: 'GET required' });
  }
  const cfg = hermesConfig();
  const options = modelOptions();
  return res.status(200).json({
    ok: true,
    gateway: 'OpenRouter',
    routing: 'lane-based (flash / worker / reasoner / judge)',
    defaultLane: 'flash',
    current: '',
    engineDefault: cfg.model,
    models: options,
    timestamp: new Date().toISOString(),
  });
}

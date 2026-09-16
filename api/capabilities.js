import { BARS_PROFILE, publicCapabilityStatus } from '../lib/bars-capabilities.js';
import { hermesHealth } from '../lib/hermes-client.js';

export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET') {
    return res.status(405).json({ ok: false, error: 'GET required' });
  }

  const hermes = await hermesHealth();
  return res.status(200).json({
    ok: true,
    service: 'BARS',
    profile: BARS_PROFILE,
    engine: {
      name: 'Hermes Agent',
      configured: hermes.configured,
      reachable: hermes.reachable,
      models: Array.isArray(hermes.models)
        ? hermes.models.map((m) => ({ id: m.id || m.name || 'hermes-agent' })).slice(0, 20)
        : [],
      error: hermes.error || null,
      upstreamStatus: hermes.upstreamStatus || null,
    },
    capabilities: publicCapabilityStatus(),
    proofRule: 'A declared capability is not considered operational until its runtime/provider reports evidence.',
    timestamp: new Date().toISOString(),
  });
}

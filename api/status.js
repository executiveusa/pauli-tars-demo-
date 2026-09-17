import { hermesHealth } from '../lib/hermes-client.js';

// Truthful BARS status endpoint: reports Hermes engine and Terabithia host plane independently.
export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store, max-age=0');

  const hermes = await hermesHealth();
  const terabithiaUrl = (process.env.TERABITHIA_REMOTE_URL || '').replace(/\/$/, '');
  const terabithiaKey = process.env.TERABITHIA_API_KEY || '';
  const remoteConfigured = Boolean(terabithiaUrl);

  let hostExecutionAttached = false;
  let activeNodes = [];

  if (remoteConfigured) {
    try {
      const headers = { Accept: 'application/json' };
      if (terabithiaKey) headers.Authorization = `Bearer ${terabithiaKey}`;
      const r = await fetch(`${terabithiaUrl}/api/v1/operators/bars/nodes`, {
        headers,
        signal: AbortSignal.timeout(4000),
      });
      if (r.ok) {
        const data = await r.json();
        activeNodes = data.nodes || [];
        const now = Date.now();
        hostExecutionAttached = activeNodes.some((n) => {
          if (n.status !== 'ONLINE') return false;
          const hbTime = new Date(n.last_heartbeat).getTime();
          return now - hbTime < 10 * 60 * 1000;
        });
      }
    } catch {
      // Status stays truthful: configured != reachable/attached.
    }
  }

  const hermesAttached = Boolean(hermes.configured && hermes.reachable);
  const gitSha = process.env.VERCEL_GIT_COMMIT_SHA || process.env.BARS_GIT_SHA || null;
  const gitRef = process.env.VERCEL_GIT_COMMIT_REF || null;
  const environment = process.env.VERCEL_ENV || process.env.NODE_ENV || null;

  return res.status(200).json({
    ok: true,
    service: 'BARS',
    operator: 'BARS',
    engine: {
      name: 'Hermes Agent',
      configured: hermes.configured,
      reachable: hermes.reachable,
      error: hermes.error || null,
      upstreamStatus: hermes.upstreamStatus || null,
    },
    controlPlane: {
      name: 'Terabithia Fleet Bus v1',
      configured: remoteConfigured,
      hostExecutionAttached,
      activeNodesCount: activeNodes.length,
      activeNodes: activeNodes.map((n) => ({
        node_id: n.node_id,
        status: n.status,
        last_heartbeat: n.last_heartbeat,
      })),
    },
    release: {
      gitSha,
      gitRef,
      environment,
      exactRevisionObservable: Boolean(gitSha),
    },
    mode: hermesAttached
      ? (hostExecutionAttached ? 'hermes+sovereign-host' : 'hermes-attached')
      : (hostExecutionAttached ? 'sovereign-host-only' : remoteConfigured ? 'control-plane-ready' : 'detached'),
    execution: hermesAttached
      ? 'hermes-tools-enabled'
      : hostExecutionAttached
        ? 'host-execution-verified'
        : 'no-agent-execution-verified',
    proofRule: 'A configured integration is not called operational until a live authenticated probe succeeds. Production verified additionally requires the exact released revision to be observable at runtime.',
    timestamp: new Date().toISOString(),
  });
}

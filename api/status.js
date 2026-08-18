export default function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  const remoteConfigured = Boolean(process.env.TERABITHIA_REMOTE_URL && process.env.TERABITHIA_API_KEY);
  res.status(200).json({
    ok: true,
    service: 'BARS',
    bus: 'Terabithia Fleet Bus v1',
    mode: remoteConfigured ? 'remote-ready' : 'web-demo',
    authority: 'Terabithia',
    operator: 'BARS',
    execution: remoteConfigured ? 'terabithia-queue' : 'demo-receipt',
    remoteControlPlaneConfigured: remoteConfigured,
    hostExecutionAttached: false,
    proofRule: 'host execution is true only after a terminal BARS evidence report',
    timestamp: new Date().toISOString()
  });
}

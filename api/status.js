export default function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.status(200).json({
    ok: true,
    service: 'BARS',
    bus: 'Terabithia Fleet Bus v1',
    mode: 'web-demo',
    authority: 'Terabithia',
    operator: 'BARS',
    execution: 'demo-receipt',
    hostExecutionAttached: false,
    timestamp: new Date().toISOString()
  });
}

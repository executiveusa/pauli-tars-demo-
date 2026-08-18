export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ ok:false, error:'POST required' });
  const body = req.body || {};
  const mission = String(body.mission || '').trim();
  if (!mission) return res.status(400).json({ ok:false, error:'mission required' });
  const id = `bars_${Date.now().toString(36)}`;
  return res.status(202).json({
    ok: true,
    missionId: id,
    target: 'BARS',
    authority: 'Terabithia',
    status: 'accepted_demo',
    mission,
    receipt: {
      received: true,
      routed: true,
      operator: 'BARS',
      hostActionExecuted: false,
      note: 'Web demo proves mission intake + governed routing receipt. Host computer execution requires an attached BARS runtime.'
    },
    timestamp: new Date().toISOString()
  });
}

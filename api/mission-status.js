const remoteUrl = () => String(process.env.TERABITHIA_REMOTE_URL || '').replace(/\/$/, '');
const authorityKey = () => String(process.env.TERABITHIA_API_KEY || '');

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET') return res.status(405).json({ ok:false, error:'GET required' });
  const missionId = String(req.query?.missionId || '').trim();
  if (!/^[A-Za-z0-9_-]{6,200}$/.test(missionId)) return res.status(400).json({ ok:false, error:'invalid missionId' });
  const base = remoteUrl();
  const key = authorityKey();
  if (!base || !key) return res.status(503).json({ ok:false, mode:'demo', error:'remote mission status not configured' });

  try {
    const upstream = await fetch(`${base}/api/v1/operators/bars/missions/${encodeURIComponent(missionId)}`, {
      headers: { 'Authorization': `Bearer ${key}` }
    });
    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) return res.status(upstream.status === 404 ? 404 : 502).json({ ok:false, error:data?.error || 'upstream failure' });
    const terminal = ['done','failed','cancelled'].includes(data.status);
    return res.status(200).json({
      ok: true,
      mode: 'remote',
      terminal,
      missionId: data.mission_id,
      status: data.status,
      capability: data.capability,
      claimedBy: data.claimed_by || null,
      barsMissionId: data.bars_mission_id || null,
      summary: data.summary || null,
      evidence: Array.isArray(data.evidence) ? data.evidence : [],
      failures: Array.isArray(data.failures) ? data.failures : [],
      updatedAt: data.updated_at || null
    });
  } catch (err) {
    return res.status(502).json({ ok:false, error:'Terabithia unavailable', detail:String(err?.message || err).slice(0,180) });
  }
}

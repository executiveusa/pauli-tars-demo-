// Acknowledges a voice pick. Selection applies in the browser session; the
// desktop runtime (/voice on server.py) persists it to config.
export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') {
    return res.status(405).json({ ok: false, error: 'POST required' });
  }
  const body = req.body || {};
  const voiceId = String(body.voice_id || '');
  if (!voiceId) {
    return res.status(400).json({ ok: false, error: 'voice_id is required' });
  }
  return res.status(200).json({
    ok: true,
    voice_id: voiceId,
    name: String(body.name || ''),
    note: 'Applied in this browser. On the hosted build, speech renders through the browser speech engine.',
    timestamp: new Date().toISOString(),
  });
}

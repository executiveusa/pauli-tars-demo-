import crypto from 'node:crypto';
import { classify } from './route.js';

const remoteUrl = () => String(process.env.TERABITHIA_REMOTE_URL || '').replace(/\/$/, '');
const authorityKey = () => String(process.env.TERABITHIA_API_KEY || '');

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ ok:false, error:'POST required' });
  const body = req.body || {};
  const mission = String(body.mission || '').trim();
  if (!mission) return res.status(400).json({ ok:false, error:'mission required' });
  if (mission.length > 4000) return res.status(400).json({ ok:false, error:'mission too long' });

  const route = classify(mission);
  const base = remoteUrl();
  const key = authorityKey();

  if (base && key) {
    const requestId = crypto.randomUUID();
    const conversationId = String(body.conversationId || `web_${requestId}`);
    const traceId = crypto.randomUUID();
    try {
      const upstream = await fetch(`${base}/api/v1/operators/bars/missions`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${key}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          request_id: requestId,
          conversation_id: conversationId,
          trace_id: traceId,
          capability: 'read_only_proof',
          user_intent: mission
        })
      });
      const data = await upstream.json().catch(() => ({}));
      if (!upstream.ok) {
        return res.status(502).json({
          ok: false,
          mode: 'remote',
          error: 'Terabithia mission creation failed',
          upstreamStatus: upstream.status,
          detail: data?.error || 'upstream failure'
        });
      }
      return res.status(202).json({
        ok: true,
        mode: 'remote',
        missionId: data.mission_id,
        target: 'BARS',
        authority: 'Terabithia',
        status: data.status,
        mission,
        capability: data.capability,
        route: { router: 'BARS Router V2', ...route },
        receipt: {
          received: true,
          queued: true,
          operator: 'BARS',
          hostActionExecuted: false,
          note: 'Mission is queued in Terabithia. Host execution is proven only after BARS reports terminal evidence.'
        },
        timestamp: new Date().toISOString()
      });
    } catch (err) {
      return res.status(502).json({ ok:false, mode:'remote', error:'Terabithia unavailable', detail:String(err?.message || err).slice(0,180) });
    }
  }

  const id = `bars_${Date.now().toString(36)}`;
  return res.status(202).json({
    ok: true,
    mode: 'demo',
    missionId: id,
    target: 'BARS',
    authority: 'Terabithia',
    status: 'accepted_demo',
    mission,
    route: { router: 'BARS Router V2', ...route },
    receipt: {
      received: true,
      routed: true,
      operator: 'BARS',
      hostActionExecuted: false,
      note: 'Demo receipt only. Configure TERABITHIA_REMOTE_URL and TERABITHIA_API_KEY on Vercel to create real remote missions.'
    },
    timestamp: new Date().toISOString()
  });
}

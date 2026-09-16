import crypto from 'node:crypto';
import { classify } from './route.js';
import { hermesConfigured, hermesRun } from '../lib/hermes-client.js';

const remoteUrl = () => String(process.env.TERABITHIA_REMOTE_URL || '').replace(/\/$/, '');
const authorityKey = () => String(process.env.TERABITHIA_API_KEY || '');

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ ok:false, error:'POST required' });

  const body = req.body || {};
  const mission = String(body.mission || '').trim();
  if (!mission) return res.status(400).json({ ok:false, error:'mission required' });
  if (mission.length > 20_000) return res.status(400).json({ ok:false, error:'mission too long' });

  const route = classify(mission);
  const requestId = crypto.randomUUID();
  const conversationId = String(body.conversationId || `bars_${requestId}`);

  // Primary execution path: Hermes owns the agent loop, skills and tool calls.
  if (hermesConfigured()) {
    try {
      const data = await hermesRun({
        input: mission,
        sessionId: conversationId,
        idempotencyKey: String(body.idempotencyKey || requestId),
      });

      return res.status(202).json({
        ok: true,
        mode: 'hermes',
        engine: 'Hermes Agent',
        runId: data.run_id || data.id || null,
        status: data.status || 'accepted',
        sessionId: data.session_id || conversationId,
        target: 'BARS',
        mission,
        route: { router: 'BARS Router V3', ...route },
        receipt: {
          received: true,
          queued: true,
          operator: 'BARS',
          engine: 'Hermes Agent',
          hostActionExecuted: false,
          note: 'Mission admission is proven. External side effects are not considered complete until Hermes run evidence reports them.',
        },
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      // Fail closed into the existing control-plane path if it is configured.
      // The error is preserved in the eventual receipt for diagnosis.
      body.hermesError = String(err?.message || err).slice(0, 180);
    }
  }

  // Existing Terabithia fallback remains available for sovereign host execution.
  const base = remoteUrl();
  const key = authorityKey();
  if (base && key) {
    const traceId = crypto.randomUUID();
    try {
      const upstream = await fetch(`${base}/api/v1/operators/bars/missions`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${key}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          request_id: requestId,
          conversation_id: conversationId,
          trace_id: traceId,
          capability: 'read_only_proof',
          user_intent: mission,
          metadata: body.hermesError ? { hermes_error: body.hermesError } : undefined,
        }),
      });
      const data = await upstream.json().catch(() => ({}));
      if (!upstream.ok) {
        return res.status(502).json({
          ok: false,
          mode: 'remote',
          error: 'Terabithia mission creation failed',
          upstreamStatus: upstream.status,
          detail: data?.error || 'upstream failure',
          hermesError: body.hermesError || null,
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
        route: { router: 'BARS Router V3', ...route },
        receipt: {
          received: true,
          queued: true,
          operator: 'BARS',
          hostActionExecuted: false,
          note: 'Mission is queued in Terabithia. Host execution is proven only after BARS reports terminal evidence.',
          hermesFallbackReason: body.hermesError || null,
        },
        timestamp: new Date().toISOString(),
      });
    } catch (err) {
      return res.status(502).json({
        ok:false,
        mode:'remote',
        error:'No execution backend available',
        hermesError: body.hermesError || null,
        terabithiaError:String(err?.message || err).slice(0,180),
      });
    }
  }

  return res.status(503).json({
    ok: false,
    mode: 'detached',
    target: 'BARS',
    engine: 'Hermes Agent',
    error: 'NoExecutionBackend',
    message: 'Attach Hermes with HERMES_REMOTE_URL + HERMES_API_KEY, or configure Terabithia as a fallback.',
    hermesError: body.hermesError || null,
    receipt: {
      received: true,
      queued: false,
      hostActionExecuted: false,
      note: 'No mission was executed or queued.',
    },
    timestamp: new Date().toISOString(),
  });
}

import { hermesChat, hermesConfigured } from '../lib/hermes-client.js';

// BARS chat: Hermes is the execution engine. We never fabricate a successful
// model/tool receipt when the runtime is detached.
export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'MethodNotAllowed', message: 'POST required' });
  }

  const { message, history, conversationId } = req.body || {};
  const prompt = String(message || '').trim();
  if (!prompt) {
    return res.status(400).json({ error: 'BadRequest', message: 'message is required.' });
  }
  if (prompt.length > 20_000) {
    return res.status(400).json({ error: 'BadRequest', message: 'message is too long.' });
  }

  if (!hermesConfigured()) {
    return res.status(503).json({
      ok: false,
      service: 'BARS',
      engine: 'Hermes Agent',
      mode: 'hermes-detached',
      error: 'HermesNotConfigured',
      message: 'BARS is online, but its Hermes execution engine is not attached yet.',
      requiredEnvironment: ['HERMES_REMOTE_URL', 'HERMES_API_KEY'],
      proof: {
        modelCalled: false,
        toolsAvailable: false,
        externalActionExecuted: false,
      },
      timestamp: new Date().toISOString(),
    });
  }

  const started = Date.now();
  try {
    const result = await hermesChat({
      message: prompt,
      history: Array.isArray(history) ? history : [],
      conversation: conversationId || 'bars-web',
    });

    return res.status(200).json({
      ok: true,
      service: 'BARS',
      engine: 'Hermes Agent',
      mode: 'hermes-attached',
      reply: result.reply || '(Hermes completed without a text response.)',
      responseId: result.responseId,
      receipt: {
        actual_model: result.model,
        status: result.status,
        latency_ms: Date.now() - started,
        usage: result.usage,
        modelCalled: true,
        externalActionExecuted: null,
        note: 'Tool outcomes must be proven by Hermes tool output or downstream evidence; this endpoint does not infer success.',
        timestamp: new Date().toISOString(),
      },
    });
  } catch (error) {
    return res.status(502).json({
      ok: false,
      service: 'BARS',
      engine: 'Hermes Agent',
      mode: 'hermes-error',
      error: error.code || 'HermesError',
      upstreamStatus: error.status || null,
      message: String(error.message || error).slice(0, 500),
      proof: { modelCalled: false, externalActionExecuted: false },
      timestamp: new Date().toISOString(),
    });
  }
}

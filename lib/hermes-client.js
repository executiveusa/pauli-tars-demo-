const stripSlash = (value = '') => String(value).replace(/\/$/, '');

export function hermesConfig(env = process.env) {
  return {
    baseUrl: stripSlash(env.HERMES_REMOTE_URL || ''),
    apiKey: String(env.HERMES_API_KEY || ''),
    model: String(env.BARS_HERMES_MODEL || 'hermes-agent'),
    profile: String(env.BARS_HERMES_PROFILE || 'bars'),
  };
}

export function hermesConfigured(env = process.env) {
  const cfg = hermesConfig(env);
  return Boolean(cfg.baseUrl && cfg.apiKey);
}

function headers(apiKey, extra = {}) {
  return {
    Authorization: `Bearer ${apiKey}`,
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...extra,
  };
}

async function hermesFetch(path, options = {}, env = process.env) {
  const cfg = hermesConfig(env);
  if (!cfg.baseUrl || !cfg.apiKey) {
    const error = new Error('Hermes runtime is not configured');
    error.code = 'HERMES_NOT_CONFIGURED';
    throw error;
  }

  const timeoutMs = Number(options.timeoutMs || 55_000);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${cfg.baseUrl}${path}`, {
      ...options,
      headers: headers(cfg.apiKey, options.headers || {}),
      signal: controller.signal,
    });

    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text.slice(0, 12_000) };
    }

    if (!response.ok) {
      const error = new Error(`Hermes request failed (${response.status})`);
      error.code = 'HERMES_UPSTREAM_ERROR';
      error.status = response.status;
      error.detail = data;
      throw error;
    }

    return data;
  } finally {
    clearTimeout(timeout);
  }
}

export async function hermesChat({ message, history = [], instructions, conversation, model }, env = process.env) {
  const cfg = hermesConfig(env);
  const input = [
    ...history
      .filter((item) => item && (item.role === 'user' || item.role === 'assistant'))
      .slice(-20)
      .map((item) => ({ role: item.role, content: String(item.content || item.message || '') })),
    { role: 'user', content: message },
  ];

  const body = {
    model: model || cfg.model,
    input,
    instructions:
      instructions ||
      'You are BARS, a Hermes-powered artist product and media operator. Use tools and skills when needed. Never claim an external action succeeded without evidence. Prefer APIs and scoped integrations over browser automation when available.',
    store: true,
  };
  if (conversation) body.conversation = String(conversation);

  const data = await hermesFetch('/v1/responses', {
    method: 'POST',
    body: JSON.stringify(body),
  }, env);

  const output = Array.isArray(data.output) ? data.output : [];
  const textParts = [];
  for (const item of output) {
    if (item?.type !== 'message') continue;
    for (const content of item.content || []) {
      if (content?.type === 'output_text' && content.text) textParts.push(content.text);
    }
  }

  return {
    raw: data,
    responseId: data.id || null,
    reply: textParts.join('\n').trim(),
    usage: data.usage || null,
    status: data.status || 'completed',
    model: data.model || model || cfg.model,
  };
}

export async function hermesRun({ input, sessionId, idempotencyKey }, env = process.env) {
  const extraHeaders = {};
  if (idempotencyKey) extraHeaders['Idempotency-Key'] = String(idempotencyKey);

  const body = { input: String(input) };
  if (sessionId) body.session_id = String(sessionId);

  return hermesFetch('/v1/runs', {
    method: 'POST',
    headers: extraHeaders,
    body: JSON.stringify(body),
    timeoutMs: 15_000,
  }, env);
}

export async function hermesRunStatus(runId, env = process.env) {
  return hermesFetch(`/v1/runs/${encodeURIComponent(runId)}`, {
    method: 'GET',
    timeoutMs: 10_000,
  }, env);
}

export async function hermesHealth(env = process.env) {
  const cfg = hermesConfig(env);
  if (!cfg.baseUrl || !cfg.apiKey) return { configured: false, reachable: false };
  try {
    const data = await hermesFetch('/v1/models', { method: 'GET', timeoutMs: 4_000 }, env);
    return { configured: true, reachable: true, models: data?.data || [] };
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      error: error.code || 'HERMES_UNREACHABLE',
      upstreamStatus: error.status || null,
    };
  }
}

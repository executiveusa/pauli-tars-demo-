// BARS connections via Composio (power-up lane). READ-ONLY first per owner
// guardrails: GET lists what's connected; POST only creates a Composio-managed
// OAuth link - the owner completes sign-in on Composio's page. No tool/action
// execution exists in this endpoint; write actions need a per-app owner word.
const BASE = 'https://backend.composio.dev/api/v3';
const USER_ID = 'bars-default';

async function capi(path, key, opts = {}) {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'x-api-key': key, 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  const body = await r.json().catch(() => ({}));
  return { status: r.status, body };
}

export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  const key = process.env.COMPOSIO_API_KEY;
  if (!key) {
    return res.status(503).json({
      ok: false, error: 'ComposioNotConfigured',
      message: 'COMPOSIO_API_KEY is not set on this deployment yet.',
      requiredEnvironment: ['COMPOSIO_API_KEY'],
    });
  }
  if (req.method === 'GET') {
    const { status, body } = await capi('/connected_accounts?limit=100', key);
    if (status !== 200) return res.status(502).json({ ok: false, error: 'ComposioError', status });
    const connections = (body.items || []).map(a => ({
      toolkit: (a.toolkit && a.toolkit.slug) || null, status: a.status, id: a.id,
    }));
    return res.status(200).json({ ok: true, count: connections.length, connections, timestamp: new Date().toISOString() });
  }
  if (req.method === 'POST') {
    const toolkit = String((req.body || {}).toolkit || '').trim().toLowerCase();
    if (!/^[a-z0-9_]{2,40}$/.test(toolkit))
      return res.status(400).json({ error: 'BadRequest', message: 'toolkit slug required (e.g. gmail).' });
    const tk = await capi('/toolkits/' + toolkit, key);
    if (tk.status !== 200)
      return res.status(404).json({ ok: false, error: 'UnknownToolkit', message: `Composio has no toolkit "${toolkit}".` });
    // auth config: reuse one for the toolkit, else create a composio-managed one
    const cfgs = await capi(`/auth_configs?limit=100`, key);
    let cfg = (cfgs.body.items || []).find(c => (c.toolkit && c.toolkit.slug) === toolkit);
    if (!cfg) {
      const made = await capi('/auth_configs', key, {
        method: 'POST',
        body: JSON.stringify({ toolkit: { slug: toolkit }, auth_config: { type: 'use_composio_managed_auth' } }),
      });
      if (made.status !== 200 && made.status !== 201)
        return res.status(502).json({ ok: false, error: 'ComposioError', status: made.status, detail: made.body && made.body.error && made.body.error.message });
      cfg = { auth_config: made.body.auth_config };
    }
    const authConfigId = cfg.auth_config && cfg.auth_config.id;
    if (!authConfigId) return res.status(502).json({ ok: false, error: 'ComposioError', message: 'no auth config id returned' });
    const link = await capi('/connected_accounts/link', key, {
      method: 'POST',
      body: JSON.stringify({ auth_config_id: authConfigId, user_id: USER_ID }),
    });
    const url = link.body.redirect_url;
    if (!url) return res.status(502).json({ ok: false, error: 'ComposioError', status: link.status, detail: link.body && link.body.error && link.body.error.message });
    return res.status(200).json({ ok: true, toolkit, link: url, expires_at: link.body.expires_at || null,
      note: 'Open this link yourself to sign the app in. Nothing connects until you complete it.' });
  }
  return res.status(405).json({ error: 'MethodNotAllowed', message: 'GET or POST required' });
}

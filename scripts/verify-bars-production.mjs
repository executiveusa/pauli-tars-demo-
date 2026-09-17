#!/usr/bin/env node

const base = String(process.env.BARS_BASE_URL || '').replace(/\/$/, '');
if (!base) throw new Error('BARS_BASE_URL is required');
const expectedSha = String(process.env.BARS_EXPECTED_SHA || '').trim();

async function request(path, init = {}) {
  const r = await fetch(`${base}${path}`, {
    redirect: 'follow',
    ...init,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(init.headers || {}) },
  });
  const text = await r.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { raw: text.slice(0, 2000) }; }
  return { ok: r.ok, status: r.status, body };
}

const failures = [];
const pass = (name, ok, detail) => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  if (!ok) failures.push({ name, detail });
};

// Phase 1: real Hermes runtime.
const status = await request('/api/status');
pass('P1 status endpoint', status.ok, status);
pass('P1 Hermes attached', Boolean(status.body?.engine?.configured && status.body?.engine?.reachable), status.body);
if (expectedSha) pass('P4 exact released revision', status.body?.release?.gitSha === expectedSha, status.body?.release);

const caps = await request('/api/capabilities');
pass('P1 capabilities endpoint', caps.ok, caps);
const ids = new Set((caps.body?.capabilities || []).map((c) => c.id));
for (const id of ['hermes-core','pauli-skill-pack','github','browser','composio','google-drive','opensuno','music-video-pipeline','interactive-store','visual-studio','loop-engineering','icm']) {
  pass(`P2 capability declared: ${id}`, ids.has(id), [...ids]);
}

const chat = await request('/api/chat', {
  method: 'POST',
  body: JSON.stringify({ message: 'Reply with exactly BARS_HERMES_PROOF_OK. Do not perform external writes.', history: [] }),
});
pass('P1 Hermes chat call', chat.ok && String(chat.body?.reply || '').includes('BARS_HERMES_PROOF_OK'), chat.body);

// Phase 2: ask Hermes for a read-only tool inventory through a real run.
const toolRun = await request('/api/mission', {
  method: 'POST',
  body: JSON.stringify({ mission: 'READ-ONLY PROOF. Enumerate the tools/skills currently available to this BARS Hermes profile, including GitHub/browser/MCP capabilities if present. Do not modify files, repositories, accounts, or external systems.' }),
});
pass('P2 tool inventory run accepted', (toolRun.status === 202 || toolRun.ok) && Boolean(toolRun.body?.runId || toolRun.body?.missionId), toolRun.body);

// Phase 3: exercise the governed artist loop without publishing/spending.
const artistRun = await request('/api/mission', {
  method: 'POST',
  body: JSON.stringify({ mission: 'BARS ARTIST LOOP PREVIEW. For a synthetic independent artist named TEST ARTIST, create a non-publishing preview plan for: single artwork, 15-second vertical teaser, one-page interactive release store, and music-video treatment. Use the Loop Engineering stages, label every provider/tool that would be called, require independent critic verification, and stop before any external write, publish, spend, or account mutation.' }),
});
pass('P3 artist production loop run accepted', (artistRun.status === 202 || artistRun.ok) && Boolean(artistRun.body?.runId || artistRun.body?.missionId), artistRun.body);

// Phase 4: production hardening surfaces must stay truthful.
pass('P4 proof rule exposed', typeof status.body?.proofRule === 'string' && status.body.proofRule.length > 10, status.body);
pass('P4 detached state cannot masquerade as production', status.body?.execution !== 'no-agent-execution-verified', status.body);

const receipt = {
  ok: failures.length === 0,
  checked_at: new Date().toISOString(),
  base,
  expected_sha: expectedSha || null,
  phase1: failures.filter((f) => f.name.startsWith('P1')).length === 0,
  phase2: failures.filter((f) => f.name.startsWith('P2')).length === 0,
  phase3: failures.filter((f) => f.name.startsWith('P3')).length === 0,
  phase4: failures.filter((f) => f.name.startsWith('P4')).length === 0,
  failures,
  tool_run_id: toolRun.body?.runId || toolRun.body?.missionId || null,
  artist_run_id: artistRun.body?.runId || artistRun.body?.missionId || null,
};
console.log(JSON.stringify(receipt, null, 2));
if (failures.length) process.exit(1);

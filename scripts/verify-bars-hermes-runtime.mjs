#!/usr/bin/env node

const base = (process.env.BARS_BASE_URL || '').replace(/\/$/, '');
if (!base) {
  console.error('BARS_BASE_URL is required');
  process.exit(2);
}

async function getJson(path, init) {
  const res = await fetch(`${base}${path}`, {
    redirect: 'follow',
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  const text = await res.text();
  let body;
  try { body = JSON.parse(text); } catch { body = { raw: text.slice(0, 1000) }; }
  return { status: res.status, ok: res.ok, body };
}

function assert(condition, message, detail) {
  if (!condition) {
    console.error(`FAIL: ${message}`);
    if (detail) console.error(JSON.stringify(detail, null, 2));
    process.exitCode = 1;
    return false;
  }
  console.log(`PASS: ${message}`);
  return true;
}

console.log(`BARS runtime proof: ${base}`);

const capabilities = await getJson('/api/capabilities');
assert(capabilities.ok, '/api/capabilities responds', capabilities);
const hermesReachable = Boolean(
  capabilities.body?.hermes?.reachable ||
  capabilities.body?.runtime?.hermes?.reachable ||
  capabilities.body?.runtime?.hermesReachable
);
assert(hermesReachable, 'Hermes is reported reachable', capabilities.body);

const status = await getJson('/api/status');
assert(status.ok, '/api/status responds', status);
const attached = Boolean(
  status.body?.hermes?.reachable ||
  status.body?.hermesAttached ||
  status.body?.runtime?.hermes?.reachable ||
  status.body?.mode === 'hermes-attached'
);
assert(attached, 'BARS reports Hermes attached', status.body);

const chat = await getJson('/api/chat', {
  method: 'POST',
  body: JSON.stringify({
    message: 'Reply with exactly BARS_HERMES_PROOF_OK and do not simulate tool execution.',
    history: [],
  }),
});
assert(chat.ok, 'BARS chat endpoint succeeds through Hermes', chat);
const chatText = String(chat.body?.reply || chat.body?.text || chat.body?.output_text || '');
assert(chatText.includes('BARS_HERMES_PROOF_OK'), 'Hermes response proof token returned', chat.body);

const mission = await getJson('/api/mission', {
  method: 'POST',
  body: JSON.stringify({
    mission: 'Perform a safe read-only runtime self-check. Do not modify files, credentials, repositories, or external systems. Return the available tool/capability names and a concise proof summary.',
  }),
});
assert(mission.ok || mission.status === 202, 'Read-only mission accepted', mission);
assert(Boolean(mission.body?.missionId || mission.body?.run_id || mission.body?.runId), 'Mission/run id returned', mission.body);

console.log(JSON.stringify({
  ok: process.exitCode !== 1,
  checked_at: new Date().toISOString(),
  base,
  capabilities_status: capabilities.status,
  status_status: status.status,
  chat_status: chat.status,
  mission_status: mission.status,
  mission_id: mission.body?.missionId || mission.body?.run_id || mission.body?.runId || null,
}, null, 2));

if (process.exitCode === 1) process.exit(1);

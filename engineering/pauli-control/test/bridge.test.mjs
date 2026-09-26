// Pauli control bridge: auth, input validation, workspace boundary, no-shell spawn, env hygiene.
// Run: npm test (node --test). Uses a fake agent binary; nothing reaches a model.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { fileURLToPath } from "node:url";

const SERVER = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "server.js");
const TOKEN = "t".repeat(40);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pauli-control-"));
const workspace = path.join(tmp, "workspace");
const outside = path.join(tmp, "outside");
const record = path.join(tmp, "agent-call.json");
const fakeAgent = path.join(tmp, "fake-agent.mjs");
fs.mkdirSync(path.join(workspace, "repo"), { recursive: true });
fs.mkdirSync(outside);
fs.symlinkSync(outside, path.join(workspace, "escape"));
fs.writeFileSync(fakeAgent, `#!/usr/bin/env node
import fs from "node:fs";
fs.writeFileSync(${JSON.stringify(record)}, JSON.stringify({ argv: process.argv.slice(2), env: process.env }));
`);
fs.chmodSync(fakeAgent, 0o755);

const servers = [];
function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer().listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}
async function startBridge(piBin) {
  const port = await freePort();
  const child = spawn(process.execPath, [SERVER], {
    env: {
      PATH: process.env.PATH, PORT: String(port), PAULI_CONTROL_TOKEN: TOKEN,
      PAULI_WORKSPACE_ROOT: workspace, PAULI_CONTROL_JOB_DIR: path.join(tmp, `jobs-${port}`), PI_BIN: piBin,
      OPENAI_API_KEY: "provider-key", PAULI_PI_AGENT_API_KEY: "personal-key",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  servers.push(child);
  await new Promise((resolve, reject) => {
    child.stdout.on("data", (d) => { if (String(d).includes("listening")) resolve(); });
    child.on("exit", (code) => reject(new Error(`bridge exited ${code}`)));
  });
  return `http://127.0.0.1:${port}`;
}
const call = async (base, method, url, body, token = TOKEN) => {
  const res = await fetch(base + url, {
    method, body: body ? JSON.stringify(body) : undefined,
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
  });
  return { status: res.status, body: await res.json() };
};
async function finished(base, jobId) {
  for (let i = 0; i < 100; i++) {
    const { body } = await call(base, "GET", `/runs/${jobId}`);
    if (body.status !== "running") return body;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error("job never finished");
}

let base;
before(async () => { base = await startBridge(fakeAgent); });
after(() => { for (const s of servers) s.kill(); fs.rmSync(tmp, { recursive: true, force: true }); });

test("health is liveness only", async () => {
  const { status, body } = await call(base, "GET", "/health", null, null);
  assert.equal(status, 200);
  assert.deepEqual(Object.keys(body).sort(), ["ok", "service"]);
});

test("run requires the bearer", async () => {
  assert.equal((await call(base, "POST", "/run", { task: "x" }, null)).status, 401);
  assert.equal((await call(base, "POST", "/run", { task: "x" }, "wrong")).status, 401);
});

test("invalid timeouts are refused before anything starts", async () => {
  for (const timeoutMinutes of [0, -5, "soon", 121]) {
    const { status } = await call(base, "POST", "/run", { task: "x", repo: "repo", timeoutMinutes });
    assert.equal(status, 400, `timeoutMinutes=${timeoutMinutes}`);
  }
});

test("flag values cannot smuggle extra flags", async () => {
  assert.equal((await call(base, "POST", "/run", { task: "x", repo: "repo", model: "--tools=bash" })).status, 400);
});

test("a symlink inside the workspace cannot escape it", async () => {
  const { status, body } = await call(base, "POST", "/run", { task: "x", repo: "escape" });
  assert.equal(status, 400);
  assert.match(body.error, /blocked/);
});

test("job ids are validated, so no path traversal", async () => {
  fs.writeFileSync(path.join(tmp, "secret.json"), JSON.stringify({ secret: "outside-the-job-dir" }));
  const traversal = await call(base, "GET", "/runs/..%2Fsecret");
  assert.equal(traversal.status, 404);
  assert.equal(traversal.body.secret, undefined);
  assert.equal((await call(base, "GET", "/runs/not-a-uuid")).status, 404);
});

test("task text reaches the agent as literal argv, not shell syntax; personal keys stay out", async () => {
  const marker = path.join(tmp, "pwned");
  const task = `summarize; touch ${marker} $(touch ${marker})`;
  const { status, body } = await call(base, "POST", "/run", { task, repo: "repo" });
  assert.equal(status, 200);
  const job = await finished(base, body.jobId);
  assert.equal(job.status, "success");
  assert.equal(fs.existsSync(marker), false, "shell metacharacters were executed");
  const seen = JSON.parse(fs.readFileSync(record, "utf8"));
  assert.ok(seen.argv.some((a) => a.includes(task)), "prompt with the literal task was not passed");
  assert.equal(seen.env.OPENAI_API_KEY, "provider-key");
  assert.equal(seen.env.PAULI_PI_AGENT_API_KEY, undefined);
  assert.equal(seen.env.PAULI_CONTROL_TOKEN, undefined);
});

test("a missing agent binary fails the job instead of crashing the bridge", async () => {
  const broken = await startBridge(path.join(tmp, "no-such-agent"));
  const { body } = await call(broken, "POST", "/run", { task: "x", repo: "repo" });
  const job = await finished(broken, body.jobId);
  assert.equal(job.status, "error");
  assert.match(job.stderr, /Could not start/);
  assert.equal((await call(broken, "GET", "/health", null, null)).status, 200);
});

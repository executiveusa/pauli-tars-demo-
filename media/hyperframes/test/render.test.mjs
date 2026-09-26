// BARS HyperFrames render service: auth, validation, workspace boundary, no-shell argv, lint gate,
// artifact evidence, stop. Run: npm test. A fake hyperframes binary stands in for Chrome + FFmpeg.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { fileURLToPath } from "node:url";

const SERVER = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "server.js");
const TOKEN = "r".repeat(40);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hf-render-"));
const workspace = path.join(tmp, "workspace");
const outside = path.join(tmp, "outside");
const calls = path.join(tmp, "calls.jsonl");
const fakeHf = path.join(tmp, "fake-hyperframes.mjs");

function project(name, { lintFails = false, slow = false } = {}) {
  const dir = path.join(workspace, name);
  fs.mkdirSync(path.join(dir, "compositions"), { recursive: true });
  fs.writeFileSync(path.join(dir, "index.html"), "<div data-composition-id='main'></div>");
  fs.writeFileSync(path.join(dir, "compositions", "intro.html"), "<template></template>");
  if (lintFails) fs.writeFileSync(path.join(dir, ".lint-fails"), "");
  if (slow) fs.writeFileSync(path.join(dir, ".slow"), "");
  return name;
}

fs.mkdirSync(workspace, { recursive: true });
fs.mkdirSync(outside);
fs.writeFileSync(path.join(outside, "index.html"), "<div></div>");
fs.symlinkSync(outside, path.join(workspace, "escape"));
// Fake CLI: records argv + env, fails lint when .lint-fails exists, writes the --output file on render.
fs.writeFileSync(fakeHf, `#!/usr/bin/env node
import fs from "node:fs";
const argv = process.argv.slice(2);
fs.appendFileSync(${JSON.stringify(calls)}, JSON.stringify({ argv, cwd: process.cwd(), env: process.env }) + "\\n");
if (argv[0] === "lint") process.exit(fs.existsSync(".lint-fails") ? 1 : 0);
if (argv[0] === "render") {
  if (fs.existsSync(".slow")) { setTimeout(() => {}, 60000); }
  else { fs.writeFileSync(argv[argv.indexOf("--output") + 1], "FAKEVIDEO"); }
}
`);
fs.chmodSync(fakeHf, 0o755);

const servers = [];
function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer().listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}
async function startService(hfBin) {
  const port = await freePort();
  const child = spawn(process.execPath, [SERVER], {
    env: {
      PATH: process.env.PATH, PORT: String(port), HYPERFRAMES_RENDER_TOKEN: TOKEN,
      HYPERFRAMES_WORKSPACE_ROOT: workspace, HYPERFRAMES_JOB_DIR: path.join(tmp, `jobs-${port}`), HF_BIN: hfBin,
      OPENAI_API_KEY: "provider-key", PAULI_PI_AGENT_API_KEY: "personal-key",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  servers.push(child);
  await new Promise((resolve, reject) => {
    child.stdout.on("data", (d) => { if (String(d).includes("listening")) resolve(); });
    child.on("exit", (code) => reject(new Error(`service exited ${code}`)));
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
async function settled(base, jobId) {
  for (let i = 0; i < 200; i++) {
    const { body } = await call(base, "GET", `/renders/${jobId}`);
    if (!["queued", "linting", "rendering"].includes(body.status)) return body;
    await new Promise((r) => setTimeout(r, 25));
  }
  throw new Error("render never settled");
}
const lastCalls = () => fs.readFileSync(calls, "utf8").trim().split("\n").map((l) => JSON.parse(l));

let base;
before(async () => { base = await startService(fakeHf); });
after(() => { for (const s of servers) s.kill(); fs.rmSync(tmp, { recursive: true, force: true }); });

test("health is liveness only; everything else needs the bearer", async () => {
  const health = await call(base, "GET", "/health", null, null);
  assert.deepEqual(health.body, { ok: true, service: "bars-hyperframes-render" });
  assert.equal((await call(base, "POST", "/render", { project: "x" }, null)).status, 401);
  assert.equal((await call(base, "POST", "/render", { project: "x" }, "wrong")).status, 401);
});

test("invalid requests are refused before anything runs", async () => {
  project("ok");
  const bad = [
    { project: "missing" },
    { project: "escape" },
    { project: "ok", format: "exe" },
    { project: "ok", quality: "max" },
    { project: "ok", fps: 1000 },
    { project: "ok", timeoutMinutes: 0 },
    { project: "ok", variables: ["not", "an", "object"] },
    { project: "ok", composition: "../../outside/index.html" },
    { project: "ok", composition: "index.js" },
  ];
  for (const body of bad) {
    assert.equal((await call(base, "POST", "/render", body)).status, 400, JSON.stringify(body));
  }
});

test("a render lints, renders with literal argv, and returns artifact evidence", async () => {
  project("launch");
  const { status, body } = await call(base, "POST", "/render", {
    project: "launch", composition: "compositions/intro.html", fps: 30, quality: "draft",
    variables: { title: "Q4; $(touch pwned)" },
  });
  assert.equal(status, 202);
  const job = await settled(base, body.jobId);
  assert.equal(job.status, "success");
  assert.equal(job.artifact.bytes, "FAKEVIDEO".length);
  assert.match(job.artifact.sha256, /^[0-9a-f]{64}$/);
  const [lint, render] = lastCalls().slice(-2);
  assert.deepEqual(lint.argv, ["lint", "."]);
  assert.equal(render.argv[0], "render");
  assert.ok(render.argv.includes("--composition") && render.argv.includes(path.join("compositions", "intro.html")));
  assert.ok(render.argv.includes("--variables-file"));
  assert.equal(fs.existsSync(path.join(workspace, "launch", "pwned")), false);
  assert.equal(render.env.HYPERFRAMES_NO_TELEMETRY, "1");
  assert.equal(render.env.OPENAI_API_KEY, undefined, "render process must not get provider keys");
  assert.equal(render.env.PAULI_PI_AGENT_API_KEY, undefined);
  assert.equal(render.env.HYPERFRAMES_RENDER_TOKEN, undefined);
});

test("a failing lint stops the job before rendering", async () => {
  project("broken", { lintFails: true });
  const { body } = await call(base, "POST", "/render", { project: "broken" });
  const job = await settled(base, body.jobId);
  assert.equal(job.status, "error");
  assert.match(job.error, /lint failed/);
  assert.equal(lastCalls().at(-1).argv[0], "lint");
});

test("one render at a time; stop is recorded truthfully", async () => {
  project("long", { slow: true });
  const first = await call(base, "POST", "/render", { project: "long" });
  assert.equal(first.status, 202);
  assert.equal((await call(base, "POST", "/render", { project: "ok" })).status, 429);
  for (let i = 0; i < 100 && (await call(base, "GET", `/renders/${first.body.jobId}`)).body.status !== "rendering"; i++) {
    await new Promise((r) => setTimeout(r, 25));
  }
  assert.equal((await call(base, "POST", `/renders/${first.body.jobId}/stop`)).status, 200);
  const job = await settled(base, first.body.jobId);
  assert.equal(job.status, "stopped");
  assert.equal(job.artifact, null);
});

test("job ids are validated, so no path traversal", async () => {
  fs.writeFileSync(path.join(tmp, "secret.json"), JSON.stringify({ secret: "outside" }));
  const r = await call(base, "GET", "/renders/..%2Fsecret");
  assert.equal(r.status, 404);
  assert.equal(r.body.secret, undefined);
});

test("a missing hyperframes binary fails the job instead of crashing the service", async () => {
  const broken = await startService(path.join(tmp, "no-such-hyperframes"));
  const { body } = await call(broken, "POST", "/render", { project: "ok" });
  const job = await settled(broken, body.jobId);
  assert.equal(job.status, "error");
  assert.match(job.stderr, /Could not start hyperframes/);
  assert.equal((await call(broken, "GET", "/health", null, null)).status, 200);
});

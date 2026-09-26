// BARS video engine. Renders HyperFrames projects (HTML compositions, github.com/heygen-com/hyperframes)
// to video on this box. Agents author a project under HYPERFRAMES_WORKSPACE_ROOT with the HyperFrames
// skills, then ask this service to lint and render it. Same safety shape as engineering/pauli-control:
// bearer on every route but /health, no shell, realpath workspace boundary, UUID job ids, loopback bind.
import "dotenv/config";
import express from "express";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const app = express();
app.use(express.json({ limit: "256kb" }));

const HERE = path.dirname(fileURLToPath(import.meta.url));
const JOB_DIR = path.resolve(process.env.HYPERFRAMES_JOB_DIR || path.join(HERE, "jobs"));
const PORT = Number(process.env.PORT || 8788);
const HOST = process.env.HOST || "127.0.0.1";
const TOKEN = process.env.HYPERFRAMES_RENDER_TOKEN;
const WORKSPACE_ROOT = path.resolve(process.env.HYPERFRAMES_WORKSPACE_ROOT || path.join(HERE, "workspace"));
const HF_BIN = process.env.HF_BIN || path.join(HERE, "node_modules", ".bin", "hyperframes");
// Chrome + FFmpeg are heavy. A bad value falls back to 1; NaN would silently disable the limit.
const parsedMaxRunning = Number(process.env.HYPERFRAMES_MAX_RUNNING || 1);
const MAX_RUNNING = Number.isInteger(parsedMaxRunning) && parsedMaxRunning >= 1 ? parsedMaxRunning : 1;
const KILL_GRACE_MS = 5000; // SIGTERM first; SIGKILL if Chrome/FFmpeg ignore it

if (!TOKEN || TOKEN.length < 32) {
  throw new Error("HYPERFRAMES_RENDER_TOKEN is missing or too short.");
}

fs.mkdirSync(JOB_DIR, { recursive: true });
fs.mkdirSync(WORKSPACE_ROOT, { recursive: true });

const running = new Map(); // jobId -> { job, child } for renders in flight
const byIdempotencyKey = new Map(); // caller's idempotency key -> jobId, so a retried mission reuses its render
const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const IDEMPOTENCY_KEY = /^[A-Za-z0-9._:-]{1,128}$/;
const TERMINAL = new Set(["success", "error", "timeout", "stopped"]);
const FORMATS = { mp4: "mp4", webm: "webm", mov: "mov", gif: "gif" };
const QUALITIES = new Set(["draft", "looks", "delivery", "standard", "high"]);
const FPS = new Set([24, 25, 30, 50, 60]);

function tokenMatches(provided) {
  const a = crypto.createHash("sha256").update(String(provided)).digest();
  const b = crypto.createHash("sha256").update(TOKEN).digest();
  return crypto.timingSafeEqual(a, b);
}

function requireAuth(req, res, next) {
  const auth = req.headers.authorization || "";
  if (!auth.startsWith("Bearer ") || !tokenMatches(auth.slice(7))) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  next();
}

// Rendering needs no provider keys; the render process gets system basics only.
function renderEnv() {
  const env = { HYPERFRAMES_NO_TELEMETRY: "1", DO_NOT_TRACK: "1" };
  for (const name of ["PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PUPPETEER_EXECUTABLE_PATH", "CHROME_PATH"]) {
    if (process.env[name] !== undefined) env[name] = process.env[name];
  }
  return env;
}

// Resolve a path the caller names, following symlinks, and refuse anything outside `root`.
function inside(root, candidate, label) {
  const resolved = path.resolve(root, String(candidate || ""));
  if (!fs.existsSync(resolved)) throw new Error(`${label} does not exist.`);
  const realRoot = fs.realpathSync(root);
  const real = fs.realpathSync(resolved);
  if (real !== realRoot && !real.startsWith(realRoot + path.sep)) {
    throw new Error(`${label} must stay inside the HyperFrames workspace.`);
  }
  return real;
}

function jobPath(id) {
  if (!JOB_ID.test(String(id))) throw new Error("Invalid job id.");
  return path.join(JOB_DIR, `${id}.json`);
}

function saveJob(job) {
  fs.writeFileSync(jobPath(job.id), JSON.stringify(job, null, 2));
}

function readJob(id) {
  if (!JOB_ID.test(String(id))) return null;
  const file = jobPath(id);
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
}

// On start, a job left queued/linting/rendering lost its process when the service stopped. Record that
// instead of reporting it as in progress forever, and rebuild the idempotency index.
function reconcileJobs() {
  for (const name of fs.readdirSync(JOB_DIR)) {
    const id = name.replace(/\.json$/, "");
    if (!JOB_ID.test(id) || name !== `${id}.json`) continue;
    let job;
    try {
      job = JSON.parse(fs.readFileSync(path.join(JOB_DIR, name), "utf8"));
    } catch {
      continue;
    }
    if (!TERMINAL.has(job.status)) {
      job.status = "error";
      job.error = "Interrupted: the render service restarted while this job was running.";
      job.finishedAt = new Date().toISOString();
      saveJob(job);
    }
    if (job.idempotencyKey) byIdempotencyKey.set(job.idempotencyKey, job.id);
    fs.rmSync(path.join(JOB_DIR, `${id}.vars.json`), { force: true });
  }
}
reconcileJobs();

// Stop a child: SIGTERM, then SIGKILL if it is still running after the grace period.
function terminate(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  const escalate = setTimeout(() => {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
  }, KILL_GRACE_MS);
  escalate.unref();
}

function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    fs.createReadStream(file)
      .on("data", (chunk) => hash.update(chunk))
      .on("end", () => resolve(hash.digest("hex")))
      .on("error", reject);
  });
}

function clip(text, max = 20000) {
  return text.length > max ? text.slice(text.length - max) : text;
}

function parseRequest(body) {
  const format = FORMATS[String(body.format || "mp4")];
  if (!format) throw new Error("format must be mp4, webm, mov or gif.");
  const quality = String(body.quality || "looks");
  if (!QUALITIES.has(quality)) throw new Error("quality must be draft, looks, delivery, standard or high.");
  const fps = body.fps === undefined ? null : Number(body.fps);
  if (fps !== null && !FPS.has(fps)) throw new Error("fps must be 24, 25, 30, 50 or 60.");
  const timeoutMinutes = Number(body.timeoutMinutes ?? 20);
  if (!Number.isFinite(timeoutMinutes) || timeoutMinutes < 1 || timeoutMinutes > 60) {
    throw new Error("timeoutMinutes must be a number from 1 to 60.");
  }
  if (body.variables !== undefined && (typeof body.variables !== "object" || body.variables === null || Array.isArray(body.variables))) {
    throw new Error("variables must be a JSON object.");
  }
  if (typeof body.project !== "string" || body.project.trim() === "") {
    throw new Error("project is required: the name of a project folder in the workspace.");
  }
  if (body.idempotencyKey !== undefined && (typeof body.idempotencyKey !== "string" || !IDEMPOTENCY_KEY.test(body.idempotencyKey))) {
    throw new Error("idempotencyKey must be 1-128 characters of letters, digits, '.', '_', ':' or '-'.");
  }
  const projectDir = inside(WORKSPACE_ROOT, body.project, "project");
  if (projectDir === fs.realpathSync(WORKSPACE_ROOT)) throw new Error("project must be a folder inside the workspace, not the workspace itself.");
  if (!fs.statSync(projectDir).isDirectory()) throw new Error("project must be a directory.");
  let composition = null;
  if (body.composition !== undefined && body.composition !== ".") {
    const file = inside(projectDir, body.composition, "composition");
    if (!file.endsWith(".html")) throw new Error("composition must be an .html file.");
    composition = path.relative(projectDir, file);
  } else if (!fs.existsSync(path.join(projectDir, "index.html"))) {
    throw new Error("project has no index.html.");
  }
  return { projectDir, composition, format, quality, fps, timeoutMinutes, variables: body.variables, idempotencyKey: body.idempotencyKey };
}

// Run one hyperframes step (lint, then render) as literal argv; resolve with its exit code.
function step(job, args, killAfterMs) {
  return new Promise((resolve) => {
    const child = spawn(HF_BIN, args, { cwd: job.projectDir, shell: false, env: renderEnv() });
    running.get(job.id).child = child;
    const timer = setTimeout(() => {
      job.status = "timeout";
      job.stderr = clip(`${job.stderr}\nTimed out after ${job.timeoutMinutes} minutes.`);
      terminate(child);
    }, Math.max(0, killAfterMs));
    child.stdout.on("data", (chunk) => { job.stdout = clip(job.stdout + chunk.toString()); });
    child.stderr.on("data", (chunk) => { job.stderr = clip(job.stderr + chunk.toString()); });
    child.on("error", (err) => {
      clearTimeout(timer);
      job.stderr = clip(`${job.stderr}\nCould not start hyperframes: ${err.message}`);
      resolve(-1);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
}

async function runJob(job, request) {
  const deadline = Date.now() + request.timeoutMinutes * 60 * 1000;
  const varsFile = path.join(JOB_DIR, `${job.id}.vars.json`);
  try {
    job.status = "linting";
    saveJob(job);
    const lint = await step(job, ["lint", "."], deadline - Date.now());
    if (job.status === "timeout" || job.status === "stopped") return;
    if (lint !== 0) {
      job.status = "error";
      job.error = "hyperframes lint failed; fix the composition before rendering.";
      return;
    }

    const args = ["render", ".", "--output", job.output, "--format", request.format, "--quality", request.quality];
    if (request.composition) args.push("--composition", request.composition);
    if (request.fps) args.push("--fps", String(request.fps));
    if (request.variables) {
      fs.writeFileSync(varsFile, JSON.stringify(request.variables), { mode: 0o600 });
      args.push("--variables-file", varsFile);
    }
    // The output folder must be a real folder inside the project: a `renders` symlink written by an
    // agent would otherwise send the render (and the reported artifact) outside the workspace.
    const rendersDir = path.join(job.projectDir, "renders");
    if (fs.existsSync(rendersDir) && fs.lstatSync(rendersDir).isSymbolicLink()) {
      throw new Error("renders/ must be a folder, not a symlink.");
    }
    fs.mkdirSync(rendersDir, { recursive: true });
    if (fs.realpathSync(rendersDir) !== path.join(fs.realpathSync(job.projectDir), "renders")) {
      throw new Error("renders/ must stay inside the project.");
    }
    job.status = "rendering";
    saveJob(job);
    const code = await step(job, args, deadline - Date.now());
    if (job.status === "timeout" || job.status === "stopped") return;
    const outputFile = path.join(job.projectDir, job.output);
    if (code !== 0 || !fs.existsSync(outputFile) || fs.statSync(outputFile).size === 0) {
      job.status = "error";
      job.error = code === 0 ? "hyperframes exited 0 but produced no output file." : `hyperframes render exited ${code}.`;
      return;
    }
    // Evidence of the actual artifact, not just an exit code.
    // Streamed, so a multi-GB video is never held in memory.
    const bytes = fs.statSync(outputFile).size;
    job.artifact = { path: outputFile, bytes, sha256: await sha256File(outputFile) };
    job.status = "success";
  } catch (error) {
    job.status = "error";
    job.error = error.message;
  } finally {
    running.delete(job.id);
    fs.rmSync(varsFile, { force: true }); // variables may hold caller data; keep them only while rendering
    job.finishedAt = new Date().toISOString();
    saveJob(job);
  }
}

app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "bars-hyperframes-render" });
});

app.post("/render", requireAuth, (req, res) => {
  let request;
  try {
    request = parseRequest(req.body || {});
  } catch (error) {
    return res.status(400).json({ error: error.message });
  }
  if (request.idempotencyKey && byIdempotencyKey.has(request.idempotencyKey)) {
    const existing = readJob(byIdempotencyKey.get(request.idempotencyKey));
    if (existing) return res.status(200).json({ jobId: existing.id, status: existing.status, project: existing.projectDir, reused: true });
  }
  if (running.size >= MAX_RUNNING) {
    return res.status(429).json({ error: "A render is already running. Retry when it finishes." });
  }
  const id = crypto.randomUUID();
  const job = {
    id,
    status: "queued",
    projectDir: request.projectDir,
    composition: request.composition,
    format: request.format,
    quality: request.quality,
    fps: request.fps,
    timeoutMinutes: request.timeoutMinutes,
    output: path.join("renders", `${id}.${request.format}`),
    idempotencyKey: request.idempotencyKey || null,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    artifact: null,
    error: null,
    stdout: "",
    stderr: "",
  };
  saveJob(job);
  if (job.idempotencyKey) byIdempotencyKey.set(job.idempotencyKey, id);
  running.set(id, { job, child: null });
  runJob(job, request);
  res.status(202).json({ jobId: id, status: job.status, project: request.projectDir });
});

app.get("/renders/:jobId", requireAuth, (req, res) => {
  const job = readJob(req.params.jobId);
  if (!job) return res.status(404).json({ error: "Render job not found." });
  res.json(job);
});

app.post("/renders/:jobId/stop", requireAuth, (req, res) => {
  const entry = JOB_ID.test(String(req.params.jobId)) ? running.get(req.params.jobId) : null;
  if (!entry) return res.status(404).json({ error: "Running render not found. It may already be finished." });
  entry.job.status = "stopped";
  saveJob(entry.job);
  terminate(entry.child);
  res.json({ ok: true, message: "Stop signal sent." });
});

app.listen(PORT, HOST, () => {
  const shownHost = HOST.includes(":") ? `[${HOST}]` : HOST;
  console.log(`BARS HyperFrames render service listening on http://${shownHost}:${PORT}`);
});

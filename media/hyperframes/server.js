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
const MAX_RUNNING = Math.max(1, Number(process.env.HYPERFRAMES_MAX_RUNNING || 1)); // Chrome + FFmpeg are heavy

if (!TOKEN || TOKEN.length < 32) {
  throw new Error("HYPERFRAMES_RENDER_TOKEN is missing or too short.");
}

fs.mkdirSync(JOB_DIR, { recursive: true });
fs.mkdirSync(WORKSPACE_ROOT, { recursive: true });

const running = new Map(); // jobId -> { job, child } for renders in flight
const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
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
  const projectDir = inside(WORKSPACE_ROOT, body.project, "project");
  if (!fs.statSync(projectDir).isDirectory()) throw new Error("project must be a directory.");
  let composition = null;
  if (body.composition !== undefined && body.composition !== ".") {
    const file = inside(projectDir, body.composition, "composition");
    if (!file.endsWith(".html")) throw new Error("composition must be an .html file.");
    composition = path.relative(projectDir, file);
  } else if (!fs.existsSync(path.join(projectDir, "index.html"))) {
    throw new Error("project has no index.html.");
  }
  return { projectDir, composition, format, quality, fps, timeoutMinutes, variables: body.variables };
}

// Run one hyperframes step (lint, then render) as literal argv; resolve with its exit code.
function step(job, args, killAfterMs) {
  return new Promise((resolve) => {
    const child = spawn(HF_BIN, args, { cwd: job.projectDir, shell: false, env: renderEnv() });
    running.get(job.id).child = child;
    const timer = setTimeout(() => {
      job.status = "timeout";
      job.stderr = clip(`${job.stderr}\nTimed out after ${job.timeoutMinutes} minutes.`);
      child.kill("SIGTERM");
    }, killAfterMs);
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
      const varsFile = path.join(JOB_DIR, `${job.id}.vars.json`);
      fs.writeFileSync(varsFile, JSON.stringify(request.variables));
      args.push("--variables-file", varsFile);
    }
    fs.mkdirSync(path.join(job.projectDir, "renders"), { recursive: true });
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
    job.artifact = {
      path: outputFile,
      bytes: fs.statSync(outputFile).size,
      sha256: crypto.createHash("sha256").update(fs.readFileSync(outputFile)).digest("hex"),
    };
    job.status = "success";
  } catch (error) {
    job.status = "error";
    job.error = error.message;
  } finally {
    running.delete(job.id);
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
    startedAt: new Date().toISOString(),
    finishedAt: null,
    artifact: null,
    error: null,
    stdout: "",
    stderr: "",
  };
  saveJob(job);
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
  if (entry.child) entry.child.kill("SIGTERM");
  res.json({ ok: true, message: "Stop signal sent." });
});

app.listen(PORT, HOST, () => {
  const shownHost = HOST.includes(":") ? `[${HOST}]` : HOST;
  console.log(`BARS HyperFrames render service listening on http://${shownHost}:${PORT}`);
});

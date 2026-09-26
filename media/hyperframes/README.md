# BARS video engine (HyperFrames)

This service renders [HyperFrames](https://github.com/heygen-com/hyperframes) projects to video on the VPS. A HyperFrames project is HTML, CSS and seekable animations. The service is part of BARS's operator lane (media).

**How it works**
1. An agent (a BARS mission, or Hermes's faceless-YouTube workflow) writes a project into `HYPERFRAMES_WORKSPACE_ROOT`, using the HyperFrames skills.
2. Terabithia sends an operator mission with `capability: "video.render"`.
3. The BARS adapter passes it to this service, which runs `hyperframes lint` and then `hyperframes render`.
4. When the render finishes, the mission receipt includes the output file's path, size and sha256.

```
Terabithia ── operator + capability video.render ──> BARS adapter (terabithia_adapter.py)
                                                         │  POST /render  (Bearer HYPERFRAMES_RENDER_TOKEN)
                                                         ▼
                                              media/hyperframes (127.0.0.1:8788)
                                                 lint → render → renders/<jobId>.mp4 (+ sha256)
```

## Mission shape

```json
{
  "target": "bars",
  "route": "operator",
  "capability": "video.render",
  "user_intent": "Render the Q4 launch video",
  "render": {
    "project": "q4-launch",
    "composition": "compositions/intro.html",
    "format": "mp4",
    "quality": "looks",
    "fps": 30,
    "variables": { "title": "Q4" },
    "timeoutMinutes": 20
  }
}
```

- `project` is required. It is a folder under the workspace; the service resolves symlinks and refuses anything that leads outside the workspace.
- `format` is `mp4`, `webm`, `mov` or `gif`.
- `quality` is `draft`, `looks` (the default), `delivery`, `standard` or `high`.
- `fps` is `24`, `25`, `30`, `50` or `60`.
- `timeoutMinutes` is from 1 to 60.

Poll `/api/terabithia/status/vid-<jobId>`. The result is `done` with the artifact as evidence, or `failed` with the reason.

## Safety

- `/health` only reports liveness. Every other route needs the bearer token `HYPERFRAMES_RENDER_TOKEN` (32 or more characters).
- `hyperframes` runs without a shell, and every argument is validated first.
- The render process gets system basics only: no provider keys, no Pi keys, no service tokens. Telemetry is off (`HYPERFRAMES_NO_TELEMETRY=1`).
- A failed lint stops the job before rendering.
- The job only counts as a success if a non-empty output file exists. HyperFrames can exit 0 without producing a file (for example when `ffprobe` is missing), and that is reported as an error.
- Only one render runs at a time (`HYPERFRAMES_MAX_RUNNING`). A second request gets a 429.
- Job ids are UUIDs. The service binds to `127.0.0.1` unless you set `HOST`.

## Run on the VPS

Requirements:
- Node 22+.
- `ffmpeg` **and** `ffprobe`: `apt-get install -y ffmpeg`.
- Chrome. HyperFrames downloads its own copy on first render, or you can set `PUPPETEER_EXECUTABLE_PATH`.
- Network access to the CDNs your compositions load (GSAP and similar), or keep those libraries inside the project.

```bash
cd media/hyperframes && npm ci
HYPERFRAMES_RENDER_TOKEN=<32+ chars> HYPERFRAMES_WORKSPACE_ROOT=/srv/video npm start   # port 8788
npx hyperframes doctor            # checks Chrome / FFmpeg / FFprobe
```

On the BARS adapter, set `HYPERFRAMES_RENDER_URL=http://127.0.0.1:8788` and the same `HYPERFRAMES_RENDER_TOKEN`.

## Agent skills and workspace

Run this once as the agent runtime user, and again whenever you want to update:

```bash
media/hyperframes/install-skills.sh /srv/video
```

It sets up two things:
1. **The official HyperFrames core skills** (`npx hyperframes skills update`). These are the `/hyperframes` router plus the core, animation, keyframes, creative, audio, CLI, registry, studio and media-use skills. They are linked into every compatible agent for that user (`~/.claude/skills`, `~/.agents/skills`, and so on).
2. **[Nate Herk's HyperFrames student kit](https://github.com/nateherkai/hyperframes-student-kit)**, installed as the agents' video workspace in `/srv/video/kit`. It is pinned to a reviewed commit and verified. It adds 15 skills (`/edit-video`, `/short-form-edit`, `/cut-silences`, `/cut-mistakes`, `/video-storytelling`, `/motion-showreel`, `/style-library`, `/make-a-video` and others), 406 motion cards, and editing tools.
   - The kit's skills call its own scripts and style library, so the whole kit is installed, not loose skill files.
   - **Not installed:** the AI Automation Society brand assets and AIS projects (the kit's notice says they are not licensed for reuse), the showcase videos, and the 287 MB of sample projects.
   - The script runs the kit's own test suite after installing.

After that, agents open `/srv/video/kit` in Claude Code or Codex and create projects under `video-projects/` (for example with `npm run new-video <name>`). Set `HYPERFRAMES_WORKSPACE_ROOT=/srv/video/kit/video-projects` so the render service renders them.

The kit pins `hyperframes` 0.7.109 for its own lint and preview. The render service renders with 0.8.78.

## Tests

`npm test` runs 7 tests against a fake `hyperframes` binary, so no Chrome is needed. They cover auth, validation, the workspace boundary, literal arguments, the lint gate, artifact evidence, one render at a time, stop, and a missing binary.

The adapter's side is covered in `tests/test_terabithia_adapter.py`.

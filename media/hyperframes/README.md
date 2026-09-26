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

So that agents can write projects, install the HyperFrames skills for the agent runtime user:

```bash
npx hyperframes skills update
```

## Tests

`npm test` runs 7 tests against a fake `hyperframes` binary, so no Chrome is needed. They cover auth, validation, the workspace boundary, literal arguments, the lint gate, artifact evidence, one render at a time, stop, and a missing binary.

The adapter's side is covered in `tests/test_terabithia_adapter.py`.

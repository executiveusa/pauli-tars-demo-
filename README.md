# TARS — Your AI Mission Agent

*"Jarvis knows. TARS does."*

TARS is an autonomous AI employee that lives on your computer. Brief it a mission by voice —
it deploys agents in the background, builds real apps, sees your screen, takes over your
mouse to show you things, and reports back out loud with the humor dial wherever you left it.

## Cross-platform (NEW)

| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Chat + voice + missions | Yes | Yes | Yes |
| 3D monolith in browser | Yes | Yes | Yes |
| Jobs board (CASE/KIPP/PLEX) | Yes | Yes | Yes |
| Floating desktop monolith | Yes (pyobjc) | Yes (PyQt6) | Yes (PyQt6) |
| Screen takeover (hands) | Yes (Quartz) | Yes (pyautogui) | Limited |
| Hue smart lights | Yes | Yes | Yes |

## Requirements

| What | Why | Required? |
|---|---|---|
| **Python 3.10+** | runs the server | Yes |
| **Anthropic API key** (or OpenRouter) | TARS's brain | Yes |
| **Claude Code CLI** (`claude`) | powers background missions | Recommended |
| OpenAI API key | live voice call + dictation | Optional |
| ElevenLabs API key | premium "Roger" voice | Optional (browser fallback) |

### Windows extra dependencies (auto-installed on first run)
```
pip install pyautogui mss Pillow PyQt6
```

### macOS extra dependencies
```
pip install pyobjc-core pyobjc-framework-Quartz
```

## Install

### Windows
1. Unzip this folder anywhere (e.g. C:\TARS).
2. Add your key: duplicate config.example.json, rename to config.json, paste your API key.
3. Launch: double-click start-tars.bat
4. Browser opens at http://localhost:4321 — say hello.

### macOS
1. Unzip this folder anywhere (e.g. ~/TARS).
2. Add your key: duplicate config.example.json, rename to config.json, paste your key.
3. Launch: double-click Launch TARS.command
4. Chrome opens at http://localhost:4321 — grant the mic when asked.

## The 10-second tour

- Hands-free — talk naturally; interrupt mid-sentence, he yields.
- LIVE voice — real-time voice call (~300ms). Share your screen and he watches it.
- Jobs board — "TARS, send CASE to research X" → agents work in background.
- BUILD missions — "build me a landing page for..." → real files, auto-opened.
- TAKEOVER — asks permission, then drives your actual mouse and shows you.
- Humor & honesty dials — set humor to 75 and see what happens.

## Safety defaults

Missions run draft-safe: TARS never sends emails, posts to social, pushes code, or
spends money — he prepares drafts and asks. TAKEOVER always asks permission first and
a red ABORT button stops it instantly. Everything runs locally; your keys never leave config.json.

## Part of The Pauli Effect

TARS is one of four agents in the X-Men architecture:
- Hermes — Orchestrator
- Cosmos (Pi) — Engineering Lead
- TARS — Builder
- Cosmos-II — Brain Keeper

MIT licensed. Built by The Pauli Effect.

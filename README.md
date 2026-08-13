# BARS — Culture DJ + Mission Operator

**BARS is the artist-facing operator for Trail Mixx and a bounded execution agent in the Pauli fleet.**

BARS combines a 3D interactive character, voice/chat, background missions, computer-use controls, media/music workflows, and Trail Mixx radio operations behind one simple front door.

> Jarvis is the presence layer. Hermes orchestrates the business. BARS operates the music/media/computer domain.

## What BARS does

- **Talk + type** — natural chat, voice input, and full-duplex live conversation.
- **Run bounded missions** — deploy named workers for research/build tasks and report back with evidence.
- **Computer use** — see the screen and, after explicit permission, control the mouse/keyboard with an emergency stop.
- **3D interface** — the browser character is the primary product surface and will expose touch-friendly body controls.
- **Trail Mixx** — BARS is the operator for the Trail Mixx radio/music experience. The station backend stays a separate system and BARS talks to it through a governed adapter rather than absorbing the whole radio codebase.
- **Music/media adapters** — generation, remix, queue, scheduling, publishing, and analysis are provider-agnostic so the product is not locked to one vendor.

## Cross-platform

| Feature | macOS | Windows | Linux |
|---|---:|---:|---:|
| Chat + voice + missions | Yes | Yes | Yes |
| 3D character in browser | Yes | Yes | Yes |
| Jobs board (CASE/KIPP/PLEX) | Yes | Yes | Yes |
| Floating desktop character | Yes (pyobjc) | Yes (PyQt6) | Yes (PyQt6) |
| Screen takeover | Yes (Quartz) | Yes (pyautogui) | Limited |
| Hue smart lights | Yes | Yes | Yes |

## Requirements

| What | Why | Required? |
|---|---|---:|
| **Python 3.10+** | Runs the local/server runtime | Yes |
| **Anthropic API key or OpenRouter-compatible route** | Conversational/reasoning brain | Yes for current runtime |
| **Claude Code CLI** (`claude`) | Powers some background missions | Recommended |
| OpenAI API key | Live voice + dictation | Optional |
| ElevenLabs API key | Premium voice | Optional |

### Windows extras

```bash
pip install pyautogui mss Pillow PyQt6
```

### macOS extras

```bash
pip install pyobjc-core pyobjc-framework-Quartz
```

## Install

### Windows

1. Put the repo in a folder such as `C:\BARS`.
2. Copy `config.example.json` to `config.json` and add the provider keys you intend to use.
3. Double-click `start-bars.bat`.
4. Open `http://localhost:4321` if the browser does not open automatically.

### macOS

1. Put the repo in a folder such as `~/BARS`.
2. Copy `config.example.json` to `config.json` and add the provider keys you intend to use.
3. Double-click `Launch BARS.command`.
4. Grant microphone/screen permissions only when you choose to use those features.

## 10-second tour

- Say or type: **“BARS, show me what you can do.”**
- Give a mission: **“Send CASE to research X.”**
- Ask to see the screen: **“BARS, look at my screen.”**
- Computer takeover always asks permission before driving the real mouse/keyboard.
- Trail Mixx controls will appear as a dedicated body/touch surface once the adapter is connected and verified.

## Safety defaults

BARS is draft-safe by default. Outward actions such as sending, posting, publishing, pushing code, spending money, or taking over the computer require the appropriate confirmation boundary. The red stop/abort control must remain available during computer-use actions.

Never commit production secrets. `config.json` and generated local tokens/state are local runtime data.

## Fleet role

The permanent Pauli fleet is:

- **Hermes / Pauli** — business orchestrator and mission delegation.
- **Pi** — private Human OS / personal second brain.
- **BARS** — computer, music, media, Trail Mixx, and bounded operator work.
- **Jarvis** — voice/phone/glasses presence layer.
- **Lightning** — independent watchdog and memory curator.

Temporary subagents/workers may be created for missions, but they are not additional permanent fleet members.

## Trail Mixx

Canonical source repo: `executiveusa/trail-mixx-source-code` (AzuraCast-based self-hosted radio stack).

BARS should integrate through a thin governed adapter with explicit read/write capabilities such as station health, now-playing, playlists, queue, and scheduling. Do not merge the entire Trail Mixx/AzuraCast codebase into BARS.

## Definition of done

A rendered page or successful HTTP response is not enough. A BARS capability is done only when a real user action reaches the real backend/tool, produces an observable result, records evidence/checkpoints where required, survives the tested failure path, and has a rollback.

Built by The Pauli Effect.

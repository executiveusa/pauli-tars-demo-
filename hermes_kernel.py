"""Hermes capability-kernel adapter for BARS.

This module does not replace BARS' HTTP/auth/memory/receipt server.  It swaps
only the inference seam, invoking a pinned Hermes installation in one-shot
programmatic mode.  No shell is used and the default provider is the keyless
OpenCode free lane; paid providers require an explicit opt-in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import shutil
import subprocess
from typing import Any, Iterable


_FREE_PROVIDERS = {"opencode-free", "free", "opencode_free"}


@dataclass
class KernelResult:
    text: str
    session_id: str = ""
    model: str = ""
    tokens: dict[str, int] = field(default_factory=dict)
    duration_ms: int = 0
    tool_events: list[dict[str, Any]] = field(default_factory=list)


class HermesKernelError(RuntimeError):
    pass


class HermesKernel:
    def __init__(self, env: dict[str, str] | None = None):
        self.env = dict(os.environ if env is None else env)
        self.enabled = self.env.get("BARS_HERMES_ENABLED", "0") == "1"
        self.binary = self.env.get("BARS_HERMES_BIN", "hermes")
        self.profile = self.env.get("BARS_HERMES_PROFILE", "bars")
        self.provider = self.env.get("BARS_HERMES_PROVIDER", "opencode-free").strip()
        self.toolsets = self.env.get(
            "BARS_HERMES_TOOLSETS",
            "hermes-api-server,video,connections",
        ).strip()
        self.skills = [
            s.strip()
            for s in self.env.get("BARS_HERMES_SKILLS", "").split(",")
            if s.strip()
        ]
        self.timeout = _bounded_int(
            self.env.get("BARS_HERMES_TIMEOUT_SECONDS"), default=240, lo=10, hi=900
        )
        self.max_turns = _bounded_int(
            self.env.get("BARS_HERMES_MAX_TURNS"), default=80, lo=1, hi=500
        )
        self.allow_paid = self.env.get("BARS_HERMES_ALLOW_PAID", "0") == "1"

    def validate(self) -> None:
        if not self.enabled:
            raise HermesKernelError("Hermes kernel is disabled (set BARS_HERMES_ENABLED=1).")
        if not self.allow_paid and self.provider not in _FREE_PROVIDERS:
            raise HermesKernelError(
                "paid/non-free Hermes provider refused; set BARS_HERMES_ALLOW_PAID=1 "
                "only after an approved budget policy is in place"
            )
        if os.path.sep in self.binary:
            if not (os.path.isfile(self.binary) and os.access(self.binary, os.X_OK)):
                raise HermesKernelError(f"Hermes executable not found: {self.binary}")
        elif shutil.which(self.binary) is None:
            raise HermesKernelError(
                f"Hermes executable '{self.binary}' is not on PATH; run the pinned bootstrap first"
            )

    def command(self) -> list[str]:
        cmd = [
            self.binary,
            "--profile",
            self.profile,
            "chat",
            "--oneshot",
            "--query-file",
            "-",
            "--format",
            "stream-json",
            "--source",
            "tool",
            "--max-turns",
            str(self.max_turns),
            "--checkpoints",
        ]
        if self.provider:
            cmd += ["--provider", self.provider]
        if self.toolsets:
            cmd += ["--toolsets", self.toolsets]
        for skill in self.skills:
            cmd += ["--skills", skill]
        return cmd

    def chat(
        self,
        *,
        system: str,
        messages: Iterable[dict[str, Any]],
        user_message: str | None = None,
        max_tokens: int = 600,
    ) -> KernelResult:
        self.validate()
        prompt = _build_query(system, messages, user_message, max_tokens=max_tokens)
        run_env = dict(self.env)
        # Never let a child inherit a flag that bypasses Hermes approvals.
        run_env.pop("HERMES_ACCEPT_HOOKS", None)
        run_env["HERMES_TUI"] = "0"
        proc = subprocess.run(
            self.command(),
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.timeout,
            env=run_env,
            check=False,
        )
        return _parse_stream(proc.stdout, proc.stderr, proc.returncode)


def install_into_bars(host_module: Any) -> HermesKernel:
    """Replace host_module.anthropic_chat while preserving every outer BARS guard."""
    kernel = HermesKernel()
    original = host_module.anthropic_chat
    fallback = os.environ.get("BARS_HERMES_FALLBACK", "0") == "1"

    def hermes_chat(system, messages, max_tokens=600, user_message=None, tools=None):
        if not kernel.enabled:
            return original(
                system,
                messages,
                max_tokens=max_tokens,
                user_message=user_message,
                tools=tools,
            )
        try:
            result = kernel.chat(
                system=system,
                messages=messages,
                user_message=user_message,
                max_tokens=max_tokens,
            )
        except Exception:
            if fallback:
                return original(
                    system,
                    messages,
                    max_tokens=max_tokens,
                    user_message=user_message,
                    tools=tools,
                )
            raise

        usage = getattr(host_module, "LAST_USAGE", None)
        if isinstance(usage, dict):
            t = result.tokens or {}
            usage.update(
                {
                    "tokens_in": int(t.get("input", 0) or 0),
                    "tokens_out": int(t.get("output", 0) or 0),
                    "cost_usd": 0.0 if kernel.provider in _FREE_PROVIDERS else None,
                    "model": result.model or f"hermes/{kernel.provider}",
                    "lane": "hermes-kernel",
                    "routing": {
                        "kernel": "hermes",
                        "profile": kernel.profile,
                        "provider": kernel.provider,
                        "toolsets": kernel.toolsets,
                        "tool_events": len(result.tool_events),
                        "session_id": result.session_id,
                    },
                }
            )
        return result.text

    host_module.anthropic_chat = hermes_chat
    return kernel


def _build_query(
    system: str,
    messages: Iterable[dict[str, Any]],
    user_message: str | None,
    *,
    max_tokens: int,
) -> str:
    clean: list[dict[str, str]] = []
    for msg in list(messages)[-12:]:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"user", "assistant"}:
            continue
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text", ""))
                for p in content
                if isinstance(p, dict) and p.get("text")
            )
        text = str(content or "").strip()
        if text:
            clean.append({"role": role, "content": text[:8000]})

    latest = (user_message or "").strip()
    if not latest and clean and clean[-1]["role"] == "user":
        latest = clean[-1]["content"]

    return (
        "BARS HOST HANDOFF\n"
        "You are the Hermes capability kernel underneath BARS. The BARS host has "
        "already handled authentication, session memory, receipts, and its own "
        "outer approval gates. Preserve the BARS voice/context below. Use your "
        "real tools when useful, but obey Hermes approval checks; never use --yolo, "
        "never invent completion, and return evidence for real actions. Dangerous "
        "or externally consequential actions must stop at the normal Hermes approval "
        "boundary when approval cannot be collected in this headless turn.\n\n"
        f"BARS SYSTEM CONTEXT:\n{system[:24000]}\n\n"
        "RECENT CONVERSATION JSON:\n"
        f"{json.dumps(clean, ensure_ascii=False)}\n\n"
        f"LATEST USER REQUEST:\n{latest[:8000]}\n\n"
        f"RESPONSE BUDGET HINT: keep the final answer within roughly {int(max_tokens)} tokens. "
        "Return the user-facing answer, not implementation chatter."
    )


def _parse_stream(stdout: str, stderr: str, returncode: int) -> KernelResult:
    final: dict[str, Any] | None = None
    text_parts: list[str] = []
    tool_events: list[dict[str, Any]] = []
    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        et = ev.get("type")
        if et == "text" and ev.get("text"):
            text_parts.append(str(ev["text"]))
        elif et in {"tool_use", "tool_result"}:
            tool_events.append(ev)
        elif et == "result":
            final = ev

    if final is None:
        detail = (stderr or stdout or "no output").strip()[-1200:]
        raise HermesKernelError(f"Hermes returned no terminal result event: {detail}")
    exit_code = int(final.get("exit_code", returncode) or 0)
    if returncode != 0 or exit_code != 0:
        detail = str(final.get("error") or stderr or final.get("text") or "unknown error")
        raise HermesKernelError(f"Hermes failed ({returncode}/{exit_code}): {detail[-1200:]}")
    text = str(final.get("text") or "").strip() or "".join(text_parts).strip()
    if not text:
        raise HermesKernelError("Hermes completed without a user-facing answer")
    tokens = final.get("tokens") if isinstance(final.get("tokens"), dict) else {}
    return KernelResult(
        text=text,
        session_id=str(final.get("session_id") or ""),
        model=str(final.get("model") or ""),
        tokens={k: int(v or 0) for k, v in tokens.items() if isinstance(v, (int, float))},
        duration_ms=int(final.get("duration_ms") or 0),
        tool_events=tool_events,
    )


def _bounded_int(raw: str | None, *, default: int, lo: int, hi: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))

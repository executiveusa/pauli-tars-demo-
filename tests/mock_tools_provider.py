# Mock provider with provider-native function-calling support.
# Serves /v1/models and /chat/completions; when the request carries tools and
# the user message is "MOCKTOOL <kind>", responds with a tool_call.
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS = {
    "deploy": ("deploy_mission", {"brief": "research rival merch pricing", "agent": "KIPP"}),
    "act": ("propose_action", {"instruction": "post the announcement"}),
    "tooladd": ("manage_tool", {"op": "add", "id": "sentry"}),
    "badargs": ("deploy_mission", {"wrong": 1}),
    "badtool": ("delete_everything", {}),
}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": m} for m in
                ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "groq/compound",
                 "whisper-large-v3-turbo", "orpheus-v1-english"]]}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body))); self.end_headers()
            self.wfile.write(body); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        model = data.get("model", "?")
        user = ""
        for m in data.get("messages", []):
            if m.get("role") == "user":
                c = m.get("content")
                user = c if isinstance(c, str) else str(c)
        if user.startswith("MOCKTOOL "):
            kind = user.split()[1]
            if not data.get("tools"):
                txt = "NO-TOOLS-SENT"
            elif kind == "notools":
                txt = "plain answer, no call needed"
            else:
                name, args = CALLS[kind]
                body = json.dumps({"choices": [{"message": {"role": "assistant",
                    "content": "MOCK-ACK",
                    "tool_calls": [{"id": "c1", "type": "function", "function":
                        {"name": name, "arguments": json.dumps(args)}}]}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7}}).encode()
                self.send_response(200); self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body))); self.end_headers()
                self.wfile.write(body); return
        elif user.startswith("MOCKSAY "):
            txt = user[len("MOCKSAY "):]
        else:
            txt = f"MOCK-REPLY[{model}]: " + user[:60]
        body = json.dumps({"choices":[{"message":{"role":"assistant","content":txt}}],
                           "usage":{"prompt_tokens":11,"completion_tokens":7}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("127.0.0.1", 9999), H).serve_forever()

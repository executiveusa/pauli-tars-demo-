import json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
                c = m.get("content"); user = c if isinstance(c, str) else str(c)
        txt = f"MOCK-REPLY[{model}]: " + user[:60]
        body = json.dumps({"choices":[{"message":{"role":"assistant","content":txt}}],
                           "usage":{"prompt_tokens":11,"completion_tokens":7}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("127.0.0.1", 9999), H).serve_forever()

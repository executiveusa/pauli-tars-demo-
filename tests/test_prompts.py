import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

subprocess.run([sys.executable, "scripts/check_prompt_sync.py"], cwd=ROOT, check=True)
source = (ROOT / "server.py").read_text(encoding="utf-8")
tree = ast.parse(source)
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "persona")
module = ast.Module(body=[node], type_ignores=[])
constitution = (ROOT / "prompts" / "constitution.md").read_text(encoding="utf-8").strip()
overlay = (ROOT / "prompts" / "overlays" / "bars.md").read_text(encoding="utf-8").strip()
namespace = {"CONSTITUTION_PROMPT": constitution, "BARS_OVERLAY_PROMPT": overlay}
exec(compile(module, "server.py", "exec"), namespace)
prompt = namespace["persona"]({"humor": 75, "honesty": 90}, spoken=True)
assert prompt.startswith(constitution + "\n\n" + overlay)
assert prompt.index(constitution) < prompt.index(overlay) < prompt.index("## Runtime settings")
assert "FLAVOR: 75 percent. AUTHENTICITY: 90 percent." in prompt
assert "two or three short sentences" in prompt
assert "four gates" in prompt.lower()
print("BARS prompt assembly tests passed.")

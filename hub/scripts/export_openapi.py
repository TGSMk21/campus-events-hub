"""Write the hand-authored contract (app/contract.py) to openapi.json for tooling and submission."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contract import SPEC  # noqa: E402

out = Path(__file__).resolve().parents[1] / "openapi.json"
out.write_text(json.dumps(SPEC, indent=2) + "\n")
print(f"Wrote {out} ({len(SPEC['paths'])} paths)")

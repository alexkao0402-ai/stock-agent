"""Publish only the isolated E3 display projection to its own cloud object."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "cache" / "researchdeps").is_dir():
    sys.path.insert(0, str(ROOT / "cache" / "researchdeps"))
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from src.config import get_secret
from src.e3_forward import DEFAULT_HOME
from src.e3_dashboard_snapshot import OBJECT_PATH, build_local_projection, create_envelope, load_display, publish_display


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    args = parser.parse_args()
    try:
        payload = build_local_projection(args.home)
        secret = get_secret("E3_DASHBOARD_SYNC_SECRET") or get_secret("V12_DASHBOARD_SYNC_SECRET")
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        envelope = create_envelope(payload, secret, source_commit=revision)
        output = ROOT / "dashboard_exports" / OBJECT_PATH
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(envelope, sort_keys=True, allow_nan=False), encoding="utf-8")
        if args.upload:
            url = get_secret("SUPABASE_URL")
            api_key = get_secret("SUPABASE_SECRET_KEY") or get_secret("SUPABASE_SERVICE_ROLE_KEY")
            publish_display(envelope, url, api_key)
            checked = load_display(url, api_key, secret)
            if checked["freeze_sha256"] != payload["freeze_sha256"] or checked["forward_sessions"] != payload["forward_sessions"]:
                raise RuntimeError("E3 publication read-back did not match")
        print(json.dumps({"status": "PUBLISHED_AND_VERIFIED" if args.upload else "EXPORTED_LOCAL_ONLY", "object": OBJECT_PATH,
                          "source_commit": revision, "generated_at": envelope["generated_at"],
                          "forward_sessions": payload["forward_sessions"], "primary_fill_count": payload["primary_fill_count"],
                          "paper_value": payload["accounts"]["E3"]["equity"], "freeze_sha256": payload["freeze_sha256"]}, indent=2))
    except Exception as exc:
        print(json.dumps({"status": "E3_DISPLAY_FAILED_CLOSED", "error_type": type(exc).__name__,
                          "message": "Publication failed; trading state was not changed. Check source integrity and server configuration."}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

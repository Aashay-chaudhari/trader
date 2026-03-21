"""Post-run check: report which analysis mode was used (CLI agent vs API).

Run as: python -m agent_trader.utils.check_mode
"""

import json
import os
from glob import glob
from pathlib import Path

from agent_trader.config.settings import get_settings


def main():
    settings = get_settings()
    data_root = Path(settings.data_dir)
    print("=" * 50)
    print("  ANALYSIS MODE REPORT")
    print("=" * 50)

    use_cli = os.environ.get("USE_CLI_AGENT", "false")
    print(f"USE_CLI_AGENT={use_cli}")
    print(f"DATA_DIR={settings.data_dir}")

    staging = data_root / "staging" / "current"
    if staging.is_dir():
        files = list(staging.iterdir())
        print(f"[OK] Staging directory exists ({len(files)} files) — CLI agent mode was attempted")
        for f in sorted(files):
            print(f"     {f.name} ({f.stat().st_size:,} bytes)")
    else:
        print("[--] No staging directory — direct API call mode was used")

    # Find latest research output
    research_files = sorted(glob(str(data_root / "research" / "*.json")), reverse=True)
    if not research_files:
        print("[--] No research output files found")
        print("=" * 50)
        return

    latest = research_files[0]
    print(f"\nLatest research: {latest}")

    try:
        with open(latest) as f:
            data = json.load(f)
    except Exception as exc:
        print(f"[ERR] Could not parse: {exc}")
        print("=" * 50)
        return

    meta = data.get("_meta", {})
    provider = meta.get("provider", "unknown")
    model = meta.get("model", "unknown")
    status = meta.get("status", "unknown")
    duration = meta.get("duration_ms", "N/A")

    print(f"Provider : {provider}")
    print(f"Model    : {model}")
    print(f"Status   : {status}")
    print(f"Duration : {duration}ms" if duration != "N/A" else "Duration : N/A")

    if "cli:" in str(provider):
        print(f"CLI Turns: {meta.get('num_turns', 'N/A')}")
        cost = meta.get("cost_usd", 0) or 0
        print(f"CLI Cost : ${cost:.4f}")
        print(f"Session  : {meta.get('session_id', 'N/A')}")
        print("\n>>> CLI AGENT MODE CONFIRMED <<<")
    else:
        attempts = meta.get("attempts", [])
        if attempts:
            for i, a in enumerate(attempts):
                print(f"Attempt {i + 1}: {a.get('provider')}/{a.get('model')} "
                      f"-> {a.get('status')} ({a.get('duration_ms', '?')}ms)")
        print("\n>>> DIRECT API MODE CONFIRMED <<<")

    print("=" * 50)


if __name__ == "__main__":
    main()

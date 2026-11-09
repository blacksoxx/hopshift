"""Start an isolated platform server for the Playwright suite.

Copies config.yaml, points every state directory at a fresh temporary folder, keeps
authentication required (the suite creates the first admin through the setup screen) and
turns off model calls so the run is offline and fast.

    python ui/e2e/serve.py --port 8765          # from the repository root
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--state-dir", default=None, help="defaults to a fresh temporary directory")
    parser.add_argument("--auth", choices=["required", "disabled"], default="required")
    args = parser.parse_args()

    state_dir = Path(args.state_dir) if args.state_dir else Path(tempfile.mkdtemp(prefix="vma-e2e-"))
    if args.state_dir and state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    config.setdefault("runtime", {})
    config["runtime"]["runs_dir"] = str(state_dir / "runs")
    config["runtime"]["checkpoint_db"] = str(state_dir / "runs" / "checkpoints.sqlite")
    config["runtime"]["platform_db"] = str(state_dir / "platform.sqlite")
    config.setdefault("security", {}).setdefault("auth", {})["mode"] = args.auth
    config["security"]["auth"]["lockout_threshold"] = 20
    config.setdefault("output", {})["llm_review_notes"] = False
    config.setdefault("logging", {})["detailed_log_file"] = str(state_dir / "app.log")
    config.setdefault("mcp", {})["enabled"] = False

    config_path = state_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    # terraform/tflint come from PATH; opa may live only in the virtualenv's bin on dev machines
    venv_bin = Path(sys.executable).resolve().parent
    os.environ["PATH"] = f"{venv_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    os.environ.setdefault("VMA_SECRET_KEY", "Qh40Wvj8j_NWRxw2EUSyCZWB7H40nhwqeYcAoniaOJ8=")
    os.environ.setdefault("TF_PLUGIN_CACHE_DIR", str(Path.home() / ".cache" / "vmware-migration-agent" / "terraform-plugins"))
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(key, None)  # the suite must never call a model

    sys.stdout.write(f"e2e server: state in {state_dir}\n")
    sys.stdout.flush()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))  # the script lives under ui/e2e; the packages live at the root
    sys.argv = ["vma", "serve", "--config", str(config_path), "--host", args.host, "--port", str(args.port)]
    from cli.main import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()

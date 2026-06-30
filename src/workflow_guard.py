from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from urllib import error, request


def build_failure_message(environ: Mapping[str, str] | None = None) -> str:
    env = environ or os.environ
    workflow_name = (env.get("WORKFLOW_NAME") or "FAIV Daily Run").strip()
    repository = (env.get("REPOSITORY") or "").strip()
    failed_job = (env.get("FAILED_JOB") or "run-pipeline").strip()
    run_url = build_run_url(env)

    lines = [
        "**GitHub Actions misslyckades**",
        f"Workflow: {workflow_name}",
        f"Jobb: {failed_job}",
    ]
    if repository:
        lines.append(f"Repo: {repository}")
    if run_url:
        lines.append(f"Run: {run_url}")
    return "\n".join(lines)


def build_run_url(environ: Mapping[str, str] | None = None) -> str:
    env = environ or os.environ
    server_url = (env.get("SERVER_URL") or "").rstrip("/")
    repository = (env.get("REPOSITORY") or "").strip().strip("/")
    run_id = (env.get("GITHUB_RUN_ID") or env.get("RUN_ID") or "").strip()
    if not server_url or not repository or not run_id:
        return ""
    return f"{server_url}/{repository}/actions/runs/{run_id}"


def notify_failure(environ: Mapping[str, str] | None = None) -> int:
    env = environ or os.environ
    webhook_url = (env.get("DISCORD_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL missing; skipping workflow failure notification.")
        return 0

    payload = json.dumps({"content": build_failure_message(env)}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            status_code = getattr(response, "status", 200)
    except error.HTTPError as exc:
        raise RuntimeError(f"Discord webhook returned HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Discord webhook request failed: {exc.reason}") from exc

    if status_code >= 400:
        raise RuntimeError(f"Discord webhook returned HTTP {status_code}")

    print("Workflow failure notification sent to Discord.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workflow notification helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("notify-failure", help="Send a Discord notification for workflow failures.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "notify-failure":
        return notify_failure()
    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""
Run agent server (port 8080) and web server (port 8010) from the app root.
Agent runs in the background; web server runs in the foreground. Ctrl+C stops both.

Usage:
    python run_agent_and_web.py
    uv run run_agent_and_web.py   # with uv (uses project venv/deps)
"""
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent


def _tee_stderr(pipe, prefix: str):
    """Read lines from pipe and print with prefix so agent logs are visible."""
    try:
        for line in iter(pipe.readline, ""):
            if line:
                print(f"{prefix}{line.rstrip()}", flush=True)
    finally:
        pipe.close()


def main():
    os.chdir(APP_ROOT)

    agent_proc = None

    def cleanup():
        nonlocal agent_proc
        if agent_proc is not None and agent_proc.poll() is None:
            print("Stopping agent server...")
            agent_proc.terminate()
            try:
                agent_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent_proc.kill()
            agent_proc = None

    def on_signal(signum, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    print("Starting agent server on port 8080...")
    agent_proc = subprocess.Popen(
        [sys.executable, "agent/start_server.py", "--port", "8080"],
        cwd=APP_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Show agent stderr in this terminal (e.g. "Failed to build agent" + traceback)
    t = threading.Thread(target=_tee_stderr, args=(agent_proc.stderr, "[agent] "), daemon=True)
    t.start()
    print(f"Agent started (PID: {agent_proc.pid})")

    time.sleep(2)
    if agent_proc.poll() is not None:
        agent_proc.wait()  # Reap process; stderr was already teed via [agent] prefix
        print("Agent failed to start (see [agent] output above).", file=sys.stderr)
        sys.exit(1)

    print("Starting web server...")
    try:
        result = subprocess.run(
            [sys.executable, "server/web_server.py"],
            cwd=APP_ROOT,
        )
        sys.exit(result.returncode)
    finally:
        cleanup()


if __name__ == "__main__":
    main()

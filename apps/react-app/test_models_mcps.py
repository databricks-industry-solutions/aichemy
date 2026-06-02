"""
Agentic test: iterate over models and MCP combos, send a simple query, report results.
Usage: uv run python test_models_mcps.py
"""

import json
import time
import uuid
import requests
import sys
from pathlib import Path

BASE = "http://localhost:8010"
TEST_QUERY = "What is the molecular weight of aspirin? Answer in one sentence."
TEST_THREAD = str(uuid.uuid4())

_models_txt = Path(__file__).parent / "public" / "models.txt"
MODELS = [m.strip() for m in _models_txt.read_text().splitlines() if m.strip()]

ALL_MCPS = [
    "pubchem", "opentargets", "pubmed", "bio/medrxiv",
    "clinical_trials", "openfda", "US_census", "cms",
    "bioportal", "biocontext", "zinc_vector_search", "drugbank", "chem_utils",
]

MCP_COMBOS = [
    ("All MCPs",           ALL_MCPS),
    ("PubChem only",       ["pubchem", "chem_utils"]),
    ("US Census only",     ["US_census", "chem_utils"]),
    ("ClinTrials + PubMed", ["clinical_trials", "pubmed", "chem_utils"]),
    ("No external MCPs",   ["zinc_vector_search", "drugbank", "chem_utils"]),
]


def rebuild(model: str, mcps: list[str]) -> dict:
    r = requests.post(f"{BASE}/api/agent/rebuild", json={"llm_endpoint": model, "enabled_mcps": mcps}, timeout=15)
    return r.json()


def wait_ready(timeout=120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE}/api/agent/status", timeout=5)
            s = r.json()
            if s.get("ready") and not s.get("building"):
                return True
            if s.get("error"):
                return False
        except Exception:
            pass
        time.sleep(3)
    return False


def send_query(thread_id: str, mcps: list[str]) -> tuple[str, str | None]:
    """Returns (text_response, error_message). One of them will be None."""
    payload = {
        "input": [{"role": "user", "content": TEST_QUERY}],
        "custom_inputs": {"thread_id": thread_id, "enabled_mcps": mcps},
    }
    try:
        resp = requests.post(f"{BASE}/api/agent/stream", json=payload, stream=True, timeout=120)
        resp.raise_for_status()

        text_chunks = []
        error_msg = None
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except json.JSONDecodeError:
                continue

            etype = ev.get("type", "")
            if etype == "error":
                error_msg = ev.get("error", {}).get("message", str(ev))
            elif etype == "response.output_text.delta":
                text_chunks.append(ev.get("delta", ""))
            elif etype == "content_block_delta":
                delta = ev.get("delta", {})
                if delta.get("type") == "text_delta":
                    text_chunks.append(delta.get("text", ""))

        text = "".join(text_chunks).strip()
        return text, error_msg
    except Exception as e:
        return "", str(e)


def run_test(label: str, model: str, mcps: list[str]) -> dict:
    print(f"\n{'='*60}")
    print(f"  TEST: {label}")
    print(f"  Model: {model}")
    print(f"  MCPs:  {mcps[:5]}{'...' if len(mcps) > 5 else ''}")
    print(f"{'='*60}")

    # Rebuild agent
    print("  → Rebuilding agent...", flush=True)
    rb = rebuild(model, mcps)
    print(f"    Rebuild response: {rb}")

    # Wait for ready
    print("  → Waiting for agent to be ready...", flush=True)
    ready = wait_ready(timeout=120)
    if not ready:
        msg = "Agent did not become ready within timeout"
        try:
            s = requests.get(f"{BASE}/api/agent/status", timeout=5).json()
            msg = s.get("error") or msg
        except Exception:
            pass
        print(f"  ✗ FAILED (rebuild): {msg}")
        return {"label": label, "model": model, "mcps": mcps, "status": "FAILED", "error": msg, "response": ""}

    print("  → Agent ready. Sending query...", flush=True)
    thread_id = str(uuid.uuid4())
    t0 = time.time()
    text, error = send_query(thread_id, mcps)
    elapsed = round(time.time() - t0, 1)

    if error:
        print(f"  ✗ FAILED ({elapsed}s): {error[:200]}")
        return {"label": label, "model": model, "mcps": mcps, "status": "FAILED", "error": error, "response": ""}

    if not text:
        msg = "Empty response (no text delta events)"
        print(f"  ✗ FAILED ({elapsed}s): {msg}")
        return {"label": label, "model": model, "mcps": mcps, "status": "FAILED", "error": msg, "response": ""}

    preview = text[:150].replace("\n", " ")
    print(f"  ✓ OK ({elapsed}s): {preview}...")
    return {"label": label, "model": model, "mcps": mcps, "status": "OK", "error": None, "response": preview}


def main():
    results = []

    print("\n" + "█"*60)
    print("  PHASE 1: Model sweep (default MCPs = all)")
    print("█"*60)

    for model in MODELS:
        r = run_test(f"Model:{model}", model, ALL_MCPS)
        results.append(r)
        time.sleep(2)

    print("\n" + "█"*60)
    print("  PHASE 2: MCP combination sweep (default model)")
    print("█"*60)

    # Reset to default model first
    default_model = "databricks-claude-opus-4-5"
    for combo_name, mcps in MCP_COMBOS:
        r = run_test(f"MCPs:{combo_name}", default_model, mcps)
        results.append(r)
        time.sleep(2)

    # Final summary
    print("\n\n" + "="*60)
    print("  FINAL REPORT")
    print("="*60)

    ok = [r for r in results if r["status"] == "OK"]
    failed = [r for r in results if r["status"] == "FAILED"]

    print(f"\n✓ PASSING ({len(ok)}):")
    for r in ok:
        print(f"   [{r['status']}] {r['label']}")

    print(f"\n✗ FAILING ({len(failed)}):")
    for r in failed:
        print(f"   [{r['status']}] {r['label']}")
        print(f"           Error: {(r['error'] or '')[:200]}")

    # Restore to default model + all MCPs
    print("\n→ Restoring default agent (claude-opus-4-5, all MCPs)...")
    rebuild(default_model, ALL_MCPS)
    wait_ready(timeout=120)
    print("  Done.")

    # Save JSON report
    with open("test_report.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nFull report saved to test_report.json")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()

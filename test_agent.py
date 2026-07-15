"""
test_agent.py
-------------
Test suite for the Autonomous Travel Agent API.
Runs both test cases defined in the specification and validates
structure, memory, and document generation.

Usage:
    python test_agent.py              # Runs all tests against a live server
    python test_agent.py --no-server  # Skip server startup (if already running)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

import requests

# Force UTF-8 output on Windows (avoids CP1252 UnicodeEncodeError for ₹, → etc.)
import sys, io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_URL  = "http://127.0.0.1:8000"
SEPARATOR = "=" * 70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pretty(obj: dict | str) -> str:
    if isinstance(obj, dict):
        return json.dumps(obj, indent=2, ensure_ascii=False)
    return str(obj)


def section(title: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {title}".encode("ascii", errors="replace").decode("ascii"))
    print(SEPARATOR)


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "✅ PASS" if condition else "❌ FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {status}  —  {label}{suffix}")
    return condition


# ---------------------------------------------------------------------------
# Test Case 1: Standard Family Trip
# ---------------------------------------------------------------------------

def test_case_1() -> bool:
    section("TEST CASE 1 -- Standard 5-Day Family Trip (Patna -> Manali)")
    payload = {
        "user_id": "tc1_family_patna",
        "query":   "Plan a 5-day trip from Patna to Manali for a family of 4, budget ₹50,000."
    }
    print(f"\n  Request payload:\n{pretty(payload)}\n")

    try:
        resp = requests.post(f"{BASE_URL}/agent", json=payload, timeout=120)
    except requests.exceptions.ConnectionError:
        print("  ❌ FAIL — Could not connect to the server. Is it running?")
        return False

    ok = resp.status_code == 200
    check("HTTP 200 OK", ok, f"got {resp.status_code}")
    if not ok:
        print(f"  Response body: {resp.text[:500]}")
        return False

    data = resp.json()
    iti  = data.get("itinerary", {})

    results = [
        check("Response has 'itinerary' key",      "itinerary"    in data),
        check("Response has 'doc_url' key",         "doc_url"      in data),
        check("Response has 'doc_filename' key",    "doc_filename" in data),
        check("Destination mentions Manali",
              "manali" in str(iti.get("destination", "")).lower(),
              f"destination={iti.get('destination')}"),
        check("Duration is 5 days",
              iti.get("duration_days") == 5,
              f"got {iti.get('duration_days')}"),
        check("Group size is 4",
              iti.get("group_size") == 4,
              f"got {iti.get('group_size')}"),
        check("Budget is ₹50,000",
              iti.get("budget_total_inr") == 50000,
              f"got {iti.get('budget_total_inr')}"),
        check("Weather info present",    bool(iti.get("weather_info"))),
        check("Flight info present",     bool(iti.get("flight_info"))),
        check("Hotel info present",      bool(iti.get("hotel_info"))),
        check("Day-by-day plan present", bool(iti.get("day_by_day"))),
        check("Has 5 day entries",
              len(iti.get("day_by_day", [])) == 5,
              f"got {len(iti.get('day_by_day', []))}"),
        check("Travel tips present",     bool(iti.get("tips"))),
        check("budget_fit key present",  "budget_fit" in iti),
    ]

    # Validate doc download
    doc_url = data.get("doc_url", "")
    if doc_url:
        dl_resp = requests.get(doc_url, timeout=30)
        results.append(check("Document downloadable (200 OK)", dl_resp.status_code == 200))
        results.append(check("Document is a .docx file",
                              "officedocument" in dl_resp.headers.get("content-type", ""),
                              dl_resp.headers.get("content-type")))

    print(f"\n  Doc URL: {doc_url}")
    print(f"\n  Summary: {iti.get('summary', '—')[:200]}")
    passed = all(results)
    print(f"\n  TEST CASE 1: {'✅ ALL PASSED' if passed else '❌ SOME FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# Test Case 2: Ambiguous Hill Station Request
# ---------------------------------------------------------------------------

def test_case_2() -> bool:
    section("TEST CASE 2 -- Ambiguous Hill Station (Patna, Rs.30,000, 4 days)")
    payload = {
        "user_id": "tc2_ambiguous_patna",
        "query":   (
            "I am leaving from Patna and have a budget of ₹30,000. "
            "I want to go to a hill station for 4 days but can't decide where. "
            "Plan the best trip for me."
        )
    }
    print(f"\n  Request payload:\n{pretty(payload)}\n")

    try:
        resp = requests.post(f"{BASE_URL}/agent", json=payload, timeout=120)
    except requests.exceptions.ConnectionError:
        print("  ❌ FAIL — Could not connect to the server. Is it running?")
        return False

    ok = resp.status_code == 200
    check("HTTP 200 OK", ok, f"got {resp.status_code}")
    if not ok:
        print(f"  Response body: {resp.text[:500]}")
        return False

    data = resp.json()
    iti  = data.get("itinerary", {})

    KNOWN_HILL_STATIONS = {
        "manali", "shimla", "mussoorie", "nainital", "darjeeling",
        "ooty", "munnar", "coorg", "kasol", "dalhousie", "mcleod ganj",
    }
    destination_str = str(iti.get("destination", "")).lower()
    picked_known    = any(h in destination_str for h in KNOWN_HILL_STATIONS)

    results = [
        check("Response has 'itinerary' key",    "itinerary"    in data),
        check("Response has 'doc_url' key",       "doc_url"      in data),
        check("Agent picked a known hill station", picked_known,
              f"destination={iti.get('destination')}"),
        check("Duration is 4 days",
              iti.get("duration_days") == 4,
              f"got {iti.get('duration_days')}"),
        check("Budget is ₹30,000",
              iti.get("budget_total_inr") == 30000,
              f"got {iti.get('budget_total_inr')}"),
        check("Weather info present",    bool(iti.get("weather_info"))),
        check("Flight info present",     bool(iti.get("flight_info"))),
        check("Day-by-day plan present", bool(iti.get("day_by_day"))),
        check("Has 4 day entries",
              len(iti.get("day_by_day", [])) == 4,
              f"got {len(iti.get('day_by_day', []))}"),
        check("Summary explains destination choice",
              len(iti.get("summary", "")) > 30),
    ]

    doc_url = data.get("doc_url", "")
    if doc_url:
        dl_resp = requests.get(doc_url, timeout=30)
        results.append(check("Document downloadable (200 OK)", dl_resp.status_code == 200))

    print(f"\n  Chosen destination: {iti.get('destination', '—')}")
    print(f"  Doc URL: {doc_url}")
    print(f"\n  Summary: {iti.get('summary', '—')[:300]}")
    passed = all(results)
    print(f"\n  TEST CASE 2: {'✅ ALL PASSED' if passed else '❌ SOME FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# Test Case 3: Memory — same user sends a follow-up
# ---------------------------------------------------------------------------

def test_case_3() -> bool:
    section("TEST CASE 3 -- Memory: Follow-up query from same user")
    user_id = "tc3_memory_user"

    # First message: set budget context
    resp1 = requests.post(f"{BASE_URL}/agent", json={
        "user_id": user_id,
        "query":   "Plan a 3-day trip from Patna to Shimla for 2 people, budget ₹20,000."
    }, timeout=120)

    ok1 = resp1.status_code == 200
    check("First query succeeds (200 OK)", ok1)
    if not ok1:
        return False

    # Second message: ask agent to remember the previous context
    resp2 = requests.post(f"{BASE_URL}/agent", json={
        "user_id": user_id,
        "query":   "Can you now extend the trip by 1 more day and suggest an extra activity, keeping the same budget?"
    }, timeout=120)

    ok2 = resp2.status_code == 200
    check("Follow-up query succeeds (200 OK)", ok2, f"got {resp2.status_code}")

    if ok2:
        iti2 = resp2.json().get("itinerary", {})
        check("Follow-up references 4 days or extended plan",
              iti2.get("duration_days") in (4, 3) or "shimla" in str(iti2.get("destination", "")).lower(),
              f"duration_days={iti2.get('duration_days')}, dest={iti2.get('destination')}")
        check("Follow-up response has day-by-day", bool(iti2.get("day_by_day")))

    # Clean up
    requests.delete(f"{BASE_URL}/memory/{user_id}", timeout=10)
    check("Memory cleared successfully", True)

    passed = ok1 and ok2
    print(f"\n  TEST CASE 3: {'✅ ALL PASSED' if passed else '❌ SOME FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# Test Case 4: Validation / Error Handling
# ---------------------------------------------------------------------------

def test_case_4() -> bool:
    section("TEST CASE 4 -- Input Validation & Error Handling")

    results = []

    # Missing required fields
    resp = requests.post(f"{BASE_URL}/agent", json={"user_id": "x"}, timeout=10)
    results.append(check("Missing 'query' → 422 Unprocessable Entity",
                          resp.status_code == 422, f"got {resp.status_code}"))

    # Empty query (too short)
    resp = requests.post(f"{BASE_URL}/agent",
                         json={"user_id": "x", "query": "hi"}, timeout=10)
    results.append(check("Too-short query → 422", resp.status_code == 422,
                          f"got {resp.status_code}"))

    # Non-existent document download
    resp = requests.get(f"{BASE_URL}/download/nonexistent_file.docx", timeout=10)
    results.append(check("Non-existent doc → 404", resp.status_code == 404,
                          f"got {resp.status_code}"))

    # Health check
    resp = requests.get(f"{BASE_URL}/health", timeout=10)
    results.append(check("Health endpoint returns 200", resp.status_code == 200))

    # Docs list
    resp = requests.get(f"{BASE_URL}/docs-list", timeout=10)
    results.append(check("Docs list endpoint returns 200", resp.status_code == 200))
    if resp.status_code == 200:
        body = resp.json()
        results.append(check("Docs list has 'documents' key", "documents" in body))

    passed = all(results)
    print(f"\n  TEST CASE 4: {'✅ ALL PASSED' if passed else '❌ SOME FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def wait_for_server(timeout: int = 30) -> bool:
    """Poll the health endpoint until the server is up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Travel Agent API test suite")
    parser.add_argument("--no-server", action="store_true",
                        help="Skip starting the server (assumes it is already running)")
    args = parser.parse_args()

    server_proc = None

    if not args.no_server:
        print("\n🚀  Starting FastAPI server …")
        server_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if not wait_for_server(timeout=30):
            print("❌  Server did not start in time.")
            server_proc.terminate()
            sys.exit(1)
        print("✅  Server is up.\n")

    try:
        results = []
        results.append(test_case_1())
        results.append(test_case_2())
        results.append(test_case_3())
        results.append(test_case_4())

        section("FINAL RESULTS")
        labels = [
            "TC1 — Standard Family Trip",
            "TC2 — Ambiguous Hill Station",
            "TC3 — Conversation Memory",
            "TC4 — Validation & Error Handling",
        ]
        for label, passed in zip(labels, results):
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status}  {label}")

        total   = len(results)
        passed  = sum(results)
        print(f"\n  {passed}/{total} test suites passed.")
        sys.exit(0 if passed == total else 1)

    finally:
        if server_proc:
            server_proc.terminate()
            print("\n🛑  Server stopped.")


if __name__ == "__main__":
    main()

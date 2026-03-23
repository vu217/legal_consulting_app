"""
Run this script once after Qdrant is confirmed running:
    python setup_collections.py

Creates two collections in Qdrant:
  - legal_statutes  (statute text, sections, provisos)
  - legal_cases     (case ratios, facts, doctrine, commentary)

Safe to run multiple times — skips collections that already exist.
"""

import httpx
import sys

QDRANT_URL = "http://localhost:6333"
VECTOR_SIZE = 768
COLLECTIONS = ["legal_statutes", "legal_cases"]


def create_collections():
    print(f"Connecting to Qdrant at {QDRANT_URL}...")

    for name in COLLECTIONS:
        check = httpx.get(f"{QDRANT_URL}/collections/{name}", timeout=10)
        if check.status_code == 200:
            print(f"  [SKIP] '{name}' already exists.")
            continue

        payload = {
            "vectors": {
                "size": VECTOR_SIZE,
                "distance": "Cosine",
            },
            "optimizers_config": {
                "default_segment_number": 2
            },
            "replication_factor": 1,
        }

        resp = httpx.put(
            f"{QDRANT_URL}/collections/{name}",
            json=payload,
            timeout=30,
        )

        if resp.status_code in (200, 201):
            print(f"  [OK]   '{name}' created.")
        else:
            print(f"  [FAIL] '{name}' — HTTP {resp.status_code}: {resp.text}")
            sys.exit(1)

    print("\nDone. Both collections are ready.")
    print(f"  legal_statutes → statute sections, provisos, definitions")
    print(f"  legal_cases    → case ratio, facts, doctrine, commentary")
    print(f"\nVerify at: {QDRANT_URL}/dashboard")


if __name__ == "__main__":
    create_collections()

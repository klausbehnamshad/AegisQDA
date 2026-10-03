from __future__ import annotations

import json
from pathlib import Path

from aegisqda.digqda_adapter import PINNED_OPEN_HASHES, _scan_outputs, _validate_digqda_contract
from aegisqda.manifests import canonical_bytes, sha256_bytes


def test_post_output_scan_chunks_large_strings(tmp_path: Path) -> None:
    payload = {"data": ["x" * 210_000 + " jane@invalid.example"]}
    path = tmp_path / "output.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _scan_outputs([path], "en") >= 1


def test_post_output_scan_routes_generated_german_separately(tmp_path: Path) -> None:
    payload = {
        "concise_description": "Die Person arbeitet im Gemeinschaftsgarten und empfindet Nützlichkeit.",
        "source_quote": "Contact jane@invalid.example",
    }
    path = tmp_path / "output.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _scan_outputs([path], "en") == 1


def test_complete_digqda_contract_is_accepted() -> None:
    digest = "a" * 64
    source_sha = "b" * 64
    manifest: dict[str, object] = {
        "library_version": "0.4",
        "contract_version": "0.1",
        "prompt_id": "QDA-GEN-DESCRIPTIVE-CODING",
        "prompt_version": "1.2",
        "prompt_source": "file",
        "backend": "ollama",
        "mode": "OPEN_DESCRIPTIVE",
        "provenance_level": "MODEL_BOUND",
        "model": "gemma3:4b",
        "model_digest": digest,
        "source_sha256": source_sha,
        "n_units": 1,
        "n_ok": 1,
        "statuses": [{"status": "OK"}],
        **PINNED_OPEN_HASHES,
    }
    coding: dict[str, object] = {"_qda_run": manifest, "results": []}
    validation: dict[str, object] = {
        "_qda_validation": {
            "validator_version": "0.4",
            "source_sha256": source_sha,
            "input_sha256": sha256_bytes(canonical_bytes(coding)),
            "result": {
                "verdict": "PASS",
                "quotes_fuzzy": 0,
                "quotes_wrong_unit": 0,
                "quotes_not_found": 0,
                "quotes_unbound": 0,
                "quotes_missing_evidence": 0,
                "locators_invalid": 0,
            },
        }
    }
    result = _validate_digqda_contract(coding, validation, "gemma3:4b", digest, source_sha)
    assert result["contract_version"] == "0.1"

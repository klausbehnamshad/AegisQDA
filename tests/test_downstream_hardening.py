from __future__ import annotations

import base64
from copy import deepcopy
import json
import importlib.util
import io
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisqda.config import load_config
from aegisqda.digqda_adapter import (
    PINNED_OPEN_HASHES,
    SEGMENT_NOTE,
    VALIDATOR_PASS_REASON,
    _analytical_language,
    _output_findings,
    _released_surrogates,
    _runtime_control_material,
    _scan_outputs,
    _validate_digqda_contract,
    analyze_run,
)
from aegisqda.errors import BoundaryError, DownstreamBlocked, IntegrityError
from aegisqda.detection import Finding
from aegisqda.generalization import KINSHIP_RULE
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from aegisqda.local_boundary import MAX_OLLAMA_METADATA_BYTES, ollama_models, validate_loopback_url
from aegisqda.privacy_gate import validate_release
from aegisqda.review_signature import verify_review_signature, verify_synthetic_review
from aegisqda.safeio import load_json
from aegisqda.workflow import scan_source, transform_run, write_review


def _signed(payload: dict[str, Any]) -> dict[str, Any]:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {
        **payload,
        "signature": {
            "algorithm": "Ed25519",
            "public_key": base64.b64encode(public).decode("ascii"),
            "key_id_sha256": sha256_bytes(public),
            "signature": base64.b64encode(key.sign(canonical_bytes(payload))).decode("ascii"),
            "trust": "SELF_SIGNED_LOCAL",
        },
    }


def _replace_artifact(path: Path, payload: dict[str, Any]) -> None:
    payload.pop("integrity_sha256", None)
    path.write_bytes(canonical_bytes(seal(payload)) + b"\n")


def _fixture_release(fixture_root: Path, tmp_path: Path) -> Path:
    run = scan_source(
        fixture_root / "en" / "safe.txt", language="en", case_id="CASE-DOWNSTREAM-TEST",
        run_root=tmp_path / "runs", synthetic=True,
    )
    assert not load_json(run / "detection-ledger.json")["findings"]
    write_review(run, "REVIEWER-TEST", [])
    transform_run(run)
    return run


def _contract_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    coding = {"_qda_run": {
        "library_version": "0.4", "contract_version": "0.1",
        "prompt_id": "QDA-GEN-DESCRIPTIVE-CODING", "prompt_version": "1.2",
        "prompt_source": "file", "backend": "ollama", "mode": "OPEN_DESCRIPTIVE",
        "provenance_level": "MODEL_BOUND", "model": "gemma3:4b",
        "model_digest": "a" * 64, "source_sha256": "b" * 64,
        "n_units": 1, "n_ok": 1, "statuses": [{"status": "OK"}],
        **PINNED_OPEN_HASHES,
    }, "results": []}
    validation = {"_qda_validation": {
        "validator_version": "0.4", "source_sha256": "b" * 64,
        "input_sha256": sha256_bytes(canonical_bytes(coding)), "result": {
            "verdict": "PASS", "quotes_fuzzy": 0, "quotes_wrong_unit": 0,
            "quotes_not_found": 0, "quotes_unbound": 0, "quotes_missing_evidence": 0,
            "locators_invalid": 0,
        },
    }}
    return coding, validation


def _output_bundle(tmp_path: Path) -> tuple[list[Path], dict[str, Any]]:
    coding, validation = _contract_payloads()
    unit = {
        "unit_id": "S01", "source_type": "srt", "source_range": "00:00:01,000 --> 00:00:02,000",
        "explicit_speaker": "not stated", "concise_description": "Die Pflege von Pflanzen wird beschrieben.",
        "narrative_function": "EVALUATION", "coding_decision": "CODES_ASSIGNED",
        "descriptive_codes": [{
            "code_label": "Pflanzenpflege", "definition": "Eine Tätigkeit im Garten wird beschrieben.",
            "status": "INDUCTIVE_CANDIDATE", "source_quote": "I enjoy tending plants.",
            "quote_locator": "00:00:01,000 --> 00:00:02,000",
        }], "uncertainty": [],
    }
    coding["results"] = [unit]
    coding["_qda_run"]["statuses"][0]["unit_id"] = "S01"
    segments = {
        "meta": {"source": "CASE-CONTROL.srt", "source_type": "srt", "source_sha256": "b" * 64,
                 "mode": "window", "n_units": 1, "note": SEGMENT_NOTE},
        "source_units": [{
            **{key: unit[key] for key in ("unit_id", "source_type", "source_range", "explicit_speaker")},
            "source_text": "I enjoy tending plants.",
        }],
    }
    validation["_qda_validation"].update({
        "validator_id": "QDA-UTIL-QUOTE-LOCATOR-VALIDATION",
        "input_sha256": sha256_bytes(canonical_bytes(coding)),
    })
    validation["_qda_validation"]["result"]["reason"] = VALIDATOR_PASS_REASON
    validation["data"] = deepcopy(coding)
    copied = validation["data"]["results"][0]
    copied["source_range_match"] = {"result": "EXACT", "cue_index": 1}
    copied["descriptive_codes"][0]["source_quote_match"] = {"result": "EXACT", "score": 100.0}
    copied["descriptive_codes"][0]["quote_locator_match"] = {"result": "EXACT", "cue_index": 1}
    paths = [tmp_path / name for name in ("segments.json", "coding.json", "validation.json")]
    for path, payload in zip(paths, (segments, coding, validation), strict=True):
        path.write_bytes(canonical_bytes(payload))
    return paths, coding


def _all_strings_are_findings(document: Any, language: str, policy: Any) -> list[Finding]:
    if not document.text:
        return []
    return [Finding(
        finding_id="F-0001", entity_type="PERSON", start=0, end=len(document.text), score=1.0,
        recognizer="SYNTHETIC-CONTROL-TEST", action="REPLACE_AND_REVIEW",
        value_sha256=sha256_bytes(document.text.encode()),
    )]


def test_language_contract_refuses_unknown_prompt_even_with_same_version() -> None:
    assert _analytical_language(PINNED_OPEN_HASHES["prompt_sha256"]) == "de"
    with pytest.raises(DownstreamBlocked, match="output-language contract"):
        _analytical_language("0" * 64)


@pytest.mark.parametrize("hash_field", list(PINNED_OPEN_HASHES))
def test_adapter_rejects_unreviewed_contract_fingerprints(hash_field: str) -> None:
    coding, validation = _contract_payloads()
    coding["_qda_run"][hash_field] = "0" * 64
    validation["_qda_validation"]["input_sha256"] = sha256_bytes(canonical_bytes(coding))
    with pytest.raises(DownstreamBlocked):
        _validate_digqda_contract(coding, validation, "gemma3:4b", "a" * 64, "b" * 64)


def test_source_and_analytical_fields_have_explicit_language_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "source_text": "TEXT", "source_quote": "QUOTE", "explicit_speaker": "SPEAKER",
        "definition": "DEFINITION", "uncertainty": ["UNCERTAINTY"],
    }
    output = tmp_path / "output.json"
    output.write_text(json.dumps(payload), encoding="utf-8")
    observed: dict[str, str] = {}

    def scan(document: Any, language: str, policy: Any) -> list[Any]:
        observed[document.text] = language
        return []

    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", scan)
    assert _scan_outputs([output], "fr") == 0
    assert observed == {
        "TEXT": "fr", "QUOTE": "fr", "SPEAKER": "fr",
        "DEFINITION": "de", "UNCERTAINTY": "de",
    }


@pytest.mark.parametrize("value", [
    "Contact jane@\ninvalid.example", "Contact jane@\r\n  invalid.example",
    "Mr. [Jane Example]", "My name is Jane\nExample and I live elsewhere.",
])
def test_output_formatting_does_not_hide_identifying_risk(tmp_path: Path, value: str) -> None:
    output = tmp_path / "output.json"
    output.write_text(json.dumps({"source_quote": value}), encoding="utf-8")
    assert _scan_outputs([output], "en") > 0


def test_nested_meta_does_not_escape_post_scan(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text(json.dumps({"results": [{"meta": {"note": "jane@invalid.example"}}]}))
    assert _scan_outputs([output], "en") > 0


def test_machine_controls_are_exempt_only_at_pinned_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, coding = _output_bundle(tmp_path)
    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", _all_strings_are_findings)
    findings = _output_findings(paths, "en", expected_coding=coding, source_label="CASE-CONTROL.srt")
    # All free text deliberately produces a synthetic hit. Provenance, SRT
    # control values, schema enums and validator EXACT must not create hits.
    assert len(findings) == 9
    free_hashes = {sha256_bytes(value.encode()) for value in (
        "I enjoy tending plants.", "Die Pflege von Pflanzen wird beschrieben.",
        "Pflanzenpflege", "Eine Tätigkeit im Garten wird beschrieben.",
    )}
    assert {item["value_sha256"] for item in findings} == free_hashes


def test_same_control_keys_elsewhere_are_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, coding = _output_bundle(tmp_path)
    coding["results"][0]["meta"] = {"status": "EXACT", "source_type": "srt"}
    coding["_qda_run"]["unknown"] = {"backend": "EVALUATION"}
    paths[1].write_bytes(canonical_bytes(coding))
    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", _all_strings_are_findings)
    findings = _output_findings([paths[1]], "en", expected_coding=coding)
    paths_found = {tuple(item["field_path"]) for item in findings}
    assert ("results", 0, "meta", "status") in paths_found
    assert ("results", 0, "meta", "source_type") in paths_found
    assert ("_qda_run", "unknown", "backend") in paths_found


def test_unknown_control_value_is_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, coding = _output_bundle(tmp_path)
    coding["results"][0]["narrative_function"] = "Jane Example"
    paths[1].write_bytes(canonical_bytes(coding))
    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", _all_strings_are_findings)
    findings = _output_findings([paths[1]], "en", expected_coding=coding)
    assert any(item["field_path"] == ["results", 0, "narrative_function"] for item in findings)


def test_validation_copy_cannot_hide_foreign_provenance(tmp_path: Path) -> None:
    paths, coding = _output_bundle(tmp_path)
    validation = load_json(paths[2])
    validation["data"]["_qda_run"]["foreign_note"] = "jane@invalid.example"
    paths[2].write_bytes(canonical_bytes(validation))
    with pytest.raises(DownstreamBlocked, match="exact coding input"):
        _scan_outputs(paths, "en", expected_coding=coding, source_label="CASE-CONTROL.srt")


def test_copied_validation_evidence_keeps_source_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, coding = _output_bundle(tmp_path)
    validation = load_json(paths[2])
    validation["data"]["results"][0]["descriptive_codes"][0]["source_quote_match"]["closest_source"] = "SOURCE-CONTEXT"
    paths[2].write_bytes(canonical_bytes(validation))
    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", _all_strings_are_findings)
    findings = _output_findings([paths[2]], "fr", expected_coding=coding)
    match = next(item for item in findings if item["field_path"][-1] == "closest_source")
    assert match["scan_language"] == "fr"


def test_detailed_output_findings_are_stable_and_source_bound(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    value = "Contact jane@invalid.example"
    output.write_bytes(canonical_bytes({"source_quote": value}))
    findings = _output_findings([output], "en", artifact_root=tmp_path)
    assert findings == _output_findings([output], "en", artifact_root=tmp_path)
    assert len(findings) == _scan_outputs([output], "en", artifact_root=tmp_path) == 1
    item = findings[0]
    assert item["artifact_path"] == "output.json"
    assert item["field_path"] == ["source_quote"]
    assert item["view_index"] == 0
    assert value[item["start"]:item["end"]] == "jane@invalid.example"
    assert item["finding_id"] == sha256_bytes(canonical_bytes({
        key: value for key, value in item.items() if key != "finding_id"
    }))


def test_only_bound_surrogate_tokens_are_masked(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text(json.dumps({"source_quote": "[PERSON_001] jane@invalid.example"}))
    assert _scan_outputs([output], "en", trusted_surrogates={"[PERSON_001]"}) > 0
    with pytest.raises(DownstreamBlocked, match="surrogate binding"):
        _scan_outputs([output], "en", trusted_surrogates={"[Jane Example]"})


def test_exemption_tokens_are_bound_to_released_bytes(tmp_path: Path) -> None:
    transformed = tmp_path / "transformed.txt"
    transformed.write_text("[PERSON_001] [FAMILY_RELATION]", encoding="utf-8")
    second = tmp_path / "second-pass.json"
    second.write_text(json.dumps({
        "surrogate_ranges": [[0, 12]], "generalizations": [{
            "entity_type": "KINSHIP", "text": "[FAMILY_RELATION]", "rule_id": KINSHIP_RULE,
            "start": 13, "end": 30,
        }],
    }), encoding="utf-8")
    release = {
        "second_pass_sha256": sha256_file(second), "transformed_sha256": sha256_file(transformed),
    }
    assert _released_surrogates(tmp_path, transformed, release) == {
        "[PERSON_001]", "[FAMILY_RELATION]",
    }
    transformed.write_text("[PERSON_001] [Jane Example]", encoding="utf-8")
    with pytest.raises(DownstreamBlocked, match="provenance changed"):
        _released_surrogates(tmp_path, transformed, release)


def test_structure_preserving_split_mention_marker_is_bound(tmp_path: Path) -> None:
    transformed = tmp_path / "transformed.txt"
    transformed.write_text("[…]", encoding="utf-8")
    second = tmp_path / "second-pass.json"
    second.write_text(json.dumps({"surrogate_ranges": [[0, 3]]}), encoding="utf-8")
    release = {"second_pass_sha256": sha256_file(second), "transformed_sha256": sha256_file(transformed)}
    assert _released_surrogates(tmp_path, transformed, release) == {"[…]"}


def test_valid_signature_cannot_self_declare_allowlist_trust() -> None:
    review = _signed({"assurance": "SELF_SIGNED_LOCAL", "state": "ACCEPTED"})
    fingerprint = review["signature"]["key_id_sha256"]
    assert verify_review_signature(review)
    assert verify_review_signature(review, trusted_key_ids={fingerprint})
    assert verify_synthetic_review(review, [])
    with pytest.raises(IntegrityError, match="trusted allowlist"):
        verify_review_signature(review, trusted_key_ids=[])
    with pytest.raises(IntegrityError, match="trusted allowlist"):
        verify_synthetic_review(review, ["0" * 64])


def test_signature_assurance_cannot_be_upgraded_by_metadata() -> None:
    review = _signed({"assurance": "SELF_SIGNED_LOCAL", "state": "ACCEPTED"})
    review["signature"]["trust"] = "TRUSTED_INSTITUTIONAL"
    with pytest.raises(IntegrityError, match="self-signed local assurance"):
        verify_synthetic_review(review, [])


@pytest.mark.parametrize("version", ["aegis-custom-strict-v1", "aegis-custom-strict-v2"])
def test_legacy_release_cannot_bypass_detector_upgrade(
    fixture_root: Path, tmp_path: Path, version: str,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    detection = load_json(run / "detection.json")
    detection["detector"]["recognizer_pack"] = version
    _replace_artifact(run / "detection.json", detection)
    with pytest.raises(DownstreamBlocked, match="current detector"):
        validate_release(run)


def test_resealed_real_data_flag_is_blocked_at_downstream_boundary(
    fixture_root: Path, tmp_path: Path,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    detection = load_json(run / "detection.json")
    detection["synthetic_only"] = False
    _replace_artifact(run / "detection.json", detection)
    with pytest.raises(DownstreamBlocked, match="real-data authorization"):
        validate_release(run)


def test_privacy_gate_enforces_configured_review_fingerprint(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    review = load_json(run / "review.json")
    review.pop("integrity_sha256")
    review["assurance"] = "SELF_SIGNED_LOCAL"
    review = _signed(review)
    _replace_artifact(run / "review.json", review)
    release = load_json(run / "privacy-release.json")
    release.update({
        "review_sha256": sha256_file(run / "review.json"), "review_assurance": "SELF_SIGNED_LOCAL",
        "review_key_id_sha256": review["signature"]["key_id_sha256"],
    })
    _replace_artifact(run / "privacy-release.json", release)
    config = load_config()
    config.authorization.trusted_review_key_ids = [review["signature"]["key_id_sha256"]]
    monkeypatch.setattr("aegisqda.privacy_gate.load_config", lambda: config)
    assert validate_release(run)[1]["review_assurance"] == "SELF_SIGNED_LOCAL"
    config.authorization.trusted_review_key_ids = ["0" * 64]
    with pytest.raises(DownstreamBlocked, match="authorized synthetic review") as exc:
        validate_release(run)
    assert isinstance(exc.value.__cause__, IntegrityError)
    assert "trusted allowlist" in str(exc.value.__cause__)


def test_changed_model_digest_blocks_before_downstream_execution(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    monkeypatch.setattr("aegisqda.digqda_adapter.ollama_models", lambda endpoint: {"gemma3:4b": "0" * 64})

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("changed digest must never invoke downstream")

    monkeypatch.setattr("aegisqda.digqda_adapter.subprocess.run", forbidden)
    with pytest.raises(DownstreamBlocked, match="approved exact tag/digest pair"):
        analyze_run(run)
    assert not (run / "digqda-attempts").exists()


def test_loopback_normalization_never_resolves_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("endpoint validation must not consult DNS")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert validate_loopback_url("http://LOCALHOST:11434/") == "http://127.0.0.1:11434"
    assert validate_loopback_url("http://[::1]:11434/") == "http://[::1]:11434"
    assert validate_loopback_url("http://127.0.0.1") == "http://127.0.0.1:80"
    with pytest.raises(BoundaryError, match="literal loopback"):
        validate_loopback_url("http://loopback-alias.invalid:11434")


@pytest.mark.parametrize("endpoint", [
    "http://[", "http://127.0.0.1:65536", "http://127.0.0.1:0",
    "http://@127.0.0.1:11434", "http://127.0.0.1:11434\n", "http://[::1%lo0]:11434",
])
def test_ambiguous_loopback_syntax_fails_closed(endpoint: str) -> None:
    with pytest.raises(BoundaryError):
        validate_loopback_url(endpoint)


def test_model_inventory_does_not_follow_redirects() -> None:
    reached_target = False

    class Target(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal reached_target
            reached_target = True
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"models": []}')

        def log_message(self, format: str, *args: Any) -> None:
            pass

    with HTTPServer(("127.0.0.1", 0), Target) as target:
        destination = f"http://127.0.0.1:{target.server_port}/api/tags"

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", destination)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                pass

        with HTTPServer(("127.0.0.1", 0), Redirect) as origin:
            workers = [Thread(target=server.serve_forever, daemon=True) for server in (target, origin)]
            for worker in workers:
                worker.start()
            try:
                with pytest.raises(BoundaryError, match="unavailable"):
                    ollama_models(f"http://127.0.0.1:{origin.server_port}")
                assert not reached_target
            finally:
                target.shutdown()
                origin.shutdown()
                for worker in workers:
                    worker.join(timeout=2)


@pytest.mark.parametrize("models", [
    [{"name": "gemma3:4b", "digest": "a" * 64}, {"name": "gemma3:4b", "digest": "b" * 64}],
    [{"name": "gemma3:4b", "digest": "a" * 64}, {"name": "broken", "digest": "unknown"}],
])
def test_incomplete_or_ambiguous_inventory_fails_closed(
    monkeypatch: pytest.MonkeyPatch, models: list[dict[str, str]],
) -> None:
    def opener(*args: Any) -> Any:
        return SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(json.dumps({"models": models}).encode()))

    monkeypatch.setattr("aegisqda.local_boundary.urllib.request.build_opener", opener)
    with pytest.raises(BoundaryError, match="model metadata"):
        ollama_models("http://127.0.0.1:11434")


def test_inventory_response_has_a_byte_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener(*args: Any) -> Any:
        return SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(b" " * (MAX_OLLAMA_METADATA_BYTES + 1)))

    monkeypatch.setattr("aegisqda.local_boundary.urllib.request.build_opener", opener)
    with pytest.raises(BoundaryError, match="inventory bound"):
        ollama_models("http://127.0.0.1:11434")


def _shim(monkeypatch: pytest.MonkeyPatch, endpoint: str = "http://127.0.0.1:11434") -> Any:
    monkeypatch.setenv("OLLAMA_HOST", endpoint)
    monkeypatch.setenv("AEGISQDA_APPROVED_MODEL", "gemma3:4b")
    monkeypatch.setenv("AEGISQDA_APPROVED_MODEL_DIGEST", "a" * 64)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            self.transport = kwargs

        def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return kwargs

        def show(self, *args: Any, **kwargs: Any) -> str:
            return "SHOW-LOCAL"

        def list(self) -> dict[str, Any]:
            return {"models": [{"model": "gemma3:4b", "digest": "a" * 64}]}

    monkeypatch.setitem(sys.modules, "ollama", SimpleNamespace(Client=Client))
    path = Path(__file__).parents[1] / "src/aegisqda/runtime_shim/sitecustomize.py"
    spec = importlib.util.spec_from_file_location("test_bound_runtime_shim", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_shim_owns_transport_and_exact_model(monkeypatch: pytest.MonkeyPatch) -> None:
    shim = _shim(monkeypatch)
    assert shim._bound_client.transport == {
        "host": "http://127.0.0.1:11434", "follow_redirects": False,
        "trust_env": False, "timeout": 3600.0,
    }
    assert shim._chat_without_thinking(model="gemma3:4b")["think"] is False
    assert shim._bound_show("gemma3:4b") == "SHOW-LOCAL"
    assert sys.modules["ollama"].list()["models"][0]["digest"] == "a" * 64
    with pytest.raises(RuntimeError, match="approved exact local model"):
        shim._chat_without_thinking(model="gemma4:e4b")
    with pytest.raises(RuntimeError, match="think=false"):
        shim._chat_without_thinking(model="gemma3:4b", think=True)


def test_runtime_shim_boundary_failure_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="could not be established"):
        _shim(monkeypatch, "http://example.invalid:11434")


def test_runtime_inventory_rechecks_selected_model_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    shim = _shim(monkeypatch)
    monkeypatch.setattr(shim._bound_client, "list", lambda: {
        "models": [{"model": "gemma3:4b", "digest": "b" * 64}],
    })
    with pytest.raises(RuntimeError, match="approved model pair"):
        shim._bound_list()


def test_cli_inventory_wrapper_uses_bound_transport_and_forbids_mutations(tmp_path: Path) -> None:
    requests: list[str] = []

    class Inventory(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"models": [{
                "name": "gemma3:4b", "model": "gemma3:4b", "digest": "a" * 64,
            }]}).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    import os
    runtime_root = Path(__file__).parents[1] / "src/aegisqda/runtime_shim"
    with HTTPServer(("127.0.0.1", 0), Inventory) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        environment = {
            **os.environ,
            "PATH": str(runtime_root), "PYTHONPATH": str(runtime_root),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(tmp_path / "unused-cache"),
            "OLLAMA_HOST": f"http://127.0.0.1:{server.server_port}",
            "AEGISQDA_APPROVED_MODEL": "gemma3:4b", "AEGISQDA_APPROVED_MODEL_DIGEST": "a" * 64,
            "AEGISQDA_RUNTIME_PYTHON": sys.executable,
            "AEGISQDA_INVENTORY_PROBE": str(runtime_root / "ollama_inventory.py"),
        }
        environment.pop("OLLAMA_API_KEY", None)
        try:
            result = subprocess.run(["ollama", "list"], env=environment, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            assert result.stdout.splitlines()[1].split()[0] == "gemma3:4b"
            assert requests == ["/api/tags"]
            blocked = subprocess.run(["ollama", "pull", "remote:latest"], env=environment, capture_output=True, text=True, timeout=30)
            assert blocked.returncode == 2
            assert requests == ["/api/tags"]
        finally:
            server.shutdown()
            worker.join(timeout=2)


def test_changed_runtime_controls_block_and_record_the_original_snapshot(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    controls = tmp_path / "controls"
    controls.mkdir()
    for name in ("__init__.py", "sitecustomize.py", "ollama_inventory.py", "ollama"):
        (controls / name).write_text("# ORIGINAL CONTROL\n", encoding="utf-8")
    (controls / "ollama").chmod(0o700)
    before_files, before_digest = _runtime_control_material(controls)
    monkeypatch.setattr("aegisqda.digqda_adapter.RUNTIME_CONTROL_ROOT", controls)
    config = load_config()
    model = next(item for item in config.models.dpo_approved_local_pairs if item.tag == "gemma3:4b")
    monkeypatch.setattr("aegisqda.digqda_adapter.ollama_models", lambda endpoint: {model.tag: model.digest})

    def changed(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        snapshot = Path(environment["PYTHONPATH"])
        assert snapshot != controls
        assert environment["PATH"].startswith(str(snapshot))
        assert Path(environment["AEGISQDA_INVENTORY_PROBE"]).parent == snapshot
        assert environment["AEGISQDA_RUNTIME_PYTHON"] == sys.executable
        assert environment["AEGISQDA_APPROVED_MODEL_DIGEST"] == model.digest
        assert environment["PYTHONPYCACHEPREFIX"] != str(controls / "__pycache__")
        assert (snapshot / "sitecustomize.py").read_bytes() == before_files["sitecustomize.py"]
        (controls / "sitecustomize.py").write_text("# CHANGED CONTROL\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("aegisqda.digqda_adapter.subprocess.run", changed)
    with pytest.raises(DownstreamBlocked, match="controls changed"):
        analyze_run(run)
    attempt = load_json(next((run / "digqda-attempts").rglob("aegis-attempt.json")))
    assert attempt["failure_kind"] == "RUNTIME_CONTROL_CHANGED"
    assert attempt["runtime_control_sha256"] == before_digest
    assert attempt["runtime_shim_sha256"] == sha256_bytes(before_files["sitecustomize.py"])
    assert not (run / "digqda-run.json").exists()


def test_resealed_release_changed_during_execution_remains_blocked(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    model = next(item for item in load_config().models.dpo_approved_local_pairs if item.tag == "gemma3:4b")
    monkeypatch.setattr("aegisqda.digqda_adapter.ollama_models", lambda endpoint: {model.tag: model.digest})

    def changed(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        path = run / "privacy-release.json"
        release = load_json(path)
        release["created_at"] = "2000-01-01T00:00:00+00:00"
        _replace_artifact(path, release)
        # This change preserves provenance validity. Its bytes nevertheless
        # differ from the release that authorized the already-started process.
        validate_release(run)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("aegisqda.digqda_adapter.subprocess.run", changed)
    with pytest.raises(DownstreamBlocked, match="release changed during"):
        analyze_run(run)
    attempt = load_json(next((run / "digqda-attempts").rglob("aegis-attempt.json")))
    assert attempt["failure_kind"] == "INPUT_RELEASE_CHANGED"
    assert not (run / "digqda-run.json").exists()


def test_output_scanner_rejects_duplicate_keys_with_hidden_values(tmp_path: Path) -> None:
    path = tmp_path / "output.json"
    path.write_bytes(b'{"description":"person@example.com","description":"ordinary activity"}')
    with pytest.raises(DownstreamBlocked, match="JSON snapshot is invalid"):
        _output_findings([path], "en")


def test_output_scanner_rejects_artifact_replaced_during_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "output.json"
    path.write_bytes(canonical_bytes({"description": "ordinary activity"}))

    def replaced(document: Any, language: str, policy: Any) -> list[Finding]:
        path.write_bytes(canonical_bytes({"description": "person@example.com"}))
        return []

    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", replaced)
    with pytest.raises(DownstreamBlocked, match="output changed during"):
        _output_findings([path], "en")


def test_changed_output_during_scan_has_no_candidate_or_final_manifest(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _fixture_release(fixture_root, tmp_path)
    model = next(item for item in load_config().models.dpo_approved_local_pairs if item.tag == "gemma3:4b")
    monkeypatch.setattr("aegisqda.digqda_adapter.ollama_models", lambda endpoint: {model.tag: model.digest})
    target: Path | None = None

    def output(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal target
        root = Path(command[command.index("--out-root") + 1])
        paths, coding = _output_bundle(root)
        source_sha = load_json(run / "privacy-release.json")["transformed_sha256"]
        coding["_qda_run"].update({"model": model.tag, "model_digest": model.digest, "source_sha256": source_sha})
        segments, validation = load_json(paths[0]), load_json(paths[2])
        segments["meta"].update({"source": "CASE-DOWNSTREAM-TEST.txt", "source_sha256": source_sha})
        validation["_qda_validation"].update({
            "source_sha256": source_sha, "input_sha256": sha256_bytes(canonical_bytes(coding)),
        })
        validation["data"]["_qda_run"] = deepcopy(coding["_qda_run"])
        for path, payload in zip(paths, (segments, coding, validation), strict=True):
            path.write_bytes(canonical_bytes(payload))
        target = paths[0]
        return subprocess.CompletedProcess(command, 0, "", "")

    def replaced(document: Any, language: str, policy: Any) -> list[Finding]:
        assert target is not None
        segments = load_json(target)
        segments["source_units"][0]["source_text"] = "person@example.com"
        target.write_bytes(canonical_bytes(segments))
        return []

    monkeypatch.setattr("aegisqda.digqda_adapter.subprocess.run", output)
    monkeypatch.setattr("aegisqda.digqda_adapter.scan_document", replaced)
    with pytest.raises(DownstreamBlocked, match="output changed during"):
        analyze_run(run)
    attempt = load_json(next((run / "digqda-attempts").rglob("aegis-attempt.json")))
    assert attempt["failure_kind"] == "OUTPUT_CHANGED_DURING_SCAN"
    assert "review_candidate" not in attempt
    assert not (run / "digqda-run.json").exists()

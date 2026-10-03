"""Deterministic synthetic regression tests for grouped PERSON mentions and audits."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from presidio_analyzer import RecognizerResult

import aegisqda.detection as detection
from aegisqda.audit import audit_run
from aegisqda.config import load_config, load_policy
from aegisqda.detection import CURRENT_RECOGNIZER_PACK, require_current_detector, scan_document
from aegisqda.errors import IntegrityError, ReviewRequired
from aegisqda.formats.document import Document, Region, parse_document_bytes
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from aegisqda.safeio import load_json
from aegisqda.workflow import scan_source, transform_run, write_review


class _SyntheticAnalyzer:
    """Single-line NER with fragment results, modeling the reported failure."""

    def analyze(self, *, text: str, **kwargs: object) -> list[RecognizerResult]:
        del kwargs
        findings: list[RecognizerResult] = []
        for pattern in (r"\[?Maria +Gonzalez\]?", r"\bMaria\b", r"\bGonzalez\b"):
            for match in re.finditer(pattern, text):
                findings.append(
                    RecognizerResult(
                        "PERSON", match.start(), match.end(), 0.9,
                        recognition_metadata={"recognizer_name": "Synthetic-spaCy-NER"},
                    )
                )
        for match in re.finditer(r"synthetic@invalid\.example", text):
            findings.append(
                RecognizerResult(
                    "EMAIL_ADDRESS", match.start(), match.end(), 0.95,
                    recognition_metadata={"recognizer_name": "Synthetic-structured"},
                )
            )
        return findings


@pytest.fixture(autouse=True)
def synthetic_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detection, "_engine", lambda language: _SyntheticAnalyzer())


def _findings(text: str, *, kind: str = "txt") -> list[detection.Finding]:
    return scan_document(
        parse_document_bytes(text.encode(), f".{kind}"), "en", load_policy(load_config())
    )


def _run(tmp_path: Path, text: str, *, kind: str = "txt") -> Path:
    source = tmp_path / f"synthetic.{kind}"
    source.write_bytes(text.encode())
    return scan_source(
        source, language="en", case_id="TEST-MENTIONS", run_root=tmp_path / "runs",
        synthetic=True,
    )


def _approve(run_dir: Path) -> None:
    write_review(
        run_dir, "TEST-REVIEWER",
        [
            {"finding_id": finding["finding_id"], "decision": "CONFIRMED"}
            for finding in load_json(run_dir / "detection-ledger.json")["findings"]
        ],
    )


def _reseal(path: Path, changes: dict[str, Any]) -> None:
    payload = load_json(path)
    payload.pop("integrity_sha256")
    payload.update(changes)
    path.write_bytes(canonical_bytes(seal(payload)) + b"\n")


def _legacy_release(
    run_dir: Path, *, leave_identifier: bool = False, version: str = "aegis-custom-strict-v2",
) -> None:
    """Simulate old sealed synthetic artifacts without weakening live runtime gates."""
    detector = load_json(run_dir / "detection.json")["detector"]
    detector["recognizer_pack"] = version
    if leave_identifier:
        _reseal(run_dir / "detection-ledger.json", {"findings": []})
    _reseal(
        run_dir / "detection.json",
        {"detector": detector, "ledger_sha256": sha256_file(run_dir / "detection-ledger.json"),
         **({"finding_count": 0} if leave_identifier else {})},
    )
    _reseal(
        run_dir / "review.json",
        {"detection_sha256": sha256_file(run_dir / "detection.json"),
         "ledger_sha256": sha256_file(run_dir / "detection-ledger.json"),
         **({"decisions": []} if leave_identifier else {})},
    )
    transformed = run_dir / "transformed.txt"
    if leave_identifier:
        transformed.write_bytes((run_dir / "source.txt").read_bytes())
        _reseal(
            run_dir / "second-pass.json",
            {"findings": [], "finding_count": 0, "surrogate_ranges": [],
             "surrogate_exempt_count": 0, "surrogate_exempt_finding_ids": []},
        )
    _reseal(
        run_dir / "privacy-release.json",
        {"detection_sha256": sha256_file(run_dir / "detection.json"),
         "ledger_sha256": sha256_file(run_dir / "detection-ledger.json"),
         "review_sha256": sha256_file(run_dir / "review.json"),
         "second_pass_sha256": sha256_file(run_dir / "second-pass.json"),
         "transformed_sha256": sha256_file(transformed)},
    )


def test_split_line_and_plain_person_are_two_mentions_with_one_canonical_value() -> None:
    findings = _findings("Maria\nGonzalez agreed. Maria Gonzalez answered.")
    assert len(findings) == 2
    assert findings[0].segments == ((0, 5), (6, 14))
    assert findings[0].canonical_value_sha256 == findings[1].canonical_value_sha256
    assert findings[0].canonical_value_sha256 == sha256_bytes(b"Maria Gonzalez")


@pytest.mark.parametrize("value", ["[Maria Gonzalez]", "[Maria\nGonzalez]"])
def test_bracketed_person_is_one_reviewable_mention(value: str) -> None:
    findings = _findings(value)
    assert len(findings) == 1
    assert (findings[0].start, findings[0].end) == (0, len(value))
    assert findings[0].canonical_value_sha256 == sha256_bytes(b"Maria Gonzalez")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_grouped_srt_transform_preserves_structure_and_coreference(
    tmp_path: Path, newline: str,
) -> None:
    source = newline.join([
        "1", "00:00:01,000 --> 00:00:03,000", "Maria", "Gonzalez", "",
        "2", "00:00:04,000 --> 00:00:06,000", "[Maria Gonzalez] agreed.", "",
    ])
    run_dir = _run(tmp_path, source, kind="srt")
    findings = load_json(run_dir / "detection-ledger.json")["findings"]
    assert len(findings) == 2
    _approve(run_dir)
    transform_run(run_dir)
    transformed = (run_dir / "transformed.srt").read_bytes().decode()
    assert transformed.count("[PERSON_001]") == 2
    assert f"[PERSON_001]{newline}[…]{newline}" in transformed
    assert "Maria" not in transformed and "Gonzalez" not in transformed
    assert parse_document_bytes(transformed.encode(), ".srt").fingerprint == parse_document_bytes(
        source.encode(), ".srt"
    ).fingerprint
    assert len(load_json(run_dir / "review.json")["decisions"]) == 2


def test_split_tail_whitespace_trimming_stops_before_next_finding(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria\nGonzalez  synthetic@invalid.example replied.\n")
    _approve(run_dir)
    transform_run(run_dir)
    assert (run_dir / "transformed.txt").read_text() == (
        "[PERSON_001]\n[EMAIL_ADDRESS_001] replied.\n"
    )


def test_person_projection_cannot_cross_srt_cue_boundary() -> None:
    text = (
        "1\n00:00:01,000 --> 00:00:03,000\nMaria\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nGonzalez\n"
    )
    findings = _findings(text, kind="srt")
    assert len(findings) == 2
    assert all("\n" not in text[finding.start:finding.end] for finding in findings)


def test_person_projection_cannot_cross_blank_paragraph() -> None:
    text = "Maria\n\nGonzalez"
    assert len(_findings(text)) == 2


def test_blank_line_remains_a_boundary_with_one_broad_content_region() -> None:
    text = "Maria\n\nGonzalez"
    document = Document("txt", text, (Region(0, len(text)),), {})
    findings = scan_document(document, "en", load_policy(load_config()))
    assert len(findings) == 2
    assert all("\n" not in text[finding.start:finding.end] for finding in findings)


@pytest.mark.parametrize("version", [None, "aegis-custom-strict-v1", "aegis-custom-strict-v2", "future"])
def test_legacy_unknown_and_missing_detector_versions_are_blocked(version: str | None) -> None:
    with pytest.raises(IntegrityError, match="fresh scan"):
        require_current_detector({"detector": {"recognizer_pack": version}})
    require_current_detector({"detector": {"recognizer_pack": CURRENT_RECOGNIZER_PACK}})


def test_legacy_run_cannot_receive_a_new_review(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    detector = load_json(run_dir / "detection.json")["detector"]
    detector["recognizer_pack"] = "aegis-custom-strict-v2"
    _reseal(run_dir / "detection.json", {"detector": detector})
    with pytest.raises(IntegrityError, match="fresh scan"):
        _approve(run_dir)
    assert not (run_dir / "review.json").exists()


def test_manual_split_person_addition_is_reviewed_once(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Synthetic\nPerson agreed.")
    value = "Synthetic\nPerson"
    write_review(
        run_dir, "TEST-REVIEWER", [],
        [{"finding_id": "A-0001", "entity_type": "PERSON", "start": 0, "end": len(value),
          "value_sha256": sha256_bytes(value.encode()), "action": "REPLACE_AND_REVIEW",
          "decision": "CONFIRMED"}],
    )
    transform_run(run_dir)
    assert (run_dir / "transformed.txt").read_text() == "[PERSON_001]\nagreed."


def test_duplicate_review_decisions_fail_closed(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed. Maria Gonzalez answered.")
    finding = load_json(run_dir / "detection-ledger.json")["findings"][0]
    with pytest.raises(ReviewRequired, match="exactly one"):
        write_review(
            run_dir, "TEST-REVIEWER",
            [{"finding_id": finding["finding_id"], "decision": "CONFIRMED"}] * 2,
        )


def test_audit_current_and_open_legacy_runs_without_writes(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    assert audit_run(run_dir)["status"] == "CURRENT"
    detector = load_json(run_dir / "detection.json")["detector"]
    detector["recognizer_pack"] = "aegis-custom-strict-v1"
    _reseal(run_dir / "detection.json", {"detector": detector})
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    report = audit_run(run_dir)
    assert report["status"] == "RESCAN_REQUIRED"
    assert report["release_authorization"] is False
    assert before == {path.name: path.read_bytes() for path in run_dir.iterdir()}
    assert "Maria" not in json.dumps(report)
    assert "Gonzalez" not in json.dumps(report)
    assert str(run_dir) not in json.dumps(report)


@pytest.mark.parametrize("source", ["Maria\nGonzalez agreed.", "[Maria Gonzalez] agreed."])
def test_audit_marks_old_split_and_bracket_residuals_affected(tmp_path: Path, source: str) -> None:
    run_dir = _run(tmp_path, source)
    _approve(run_dir)
    transform_run(run_dir)
    _legacy_release(run_dir, leave_identifier=True)
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    report = audit_run(run_dir)
    assert report["status"] == "AFFECTED"
    assert set(report["risk_codes"]) == {
        "LEGACY_DETECTOR", "PERSON_MENTION_NOT_REVIEWED_AS_UNIT", "RESIDUAL_IDENTIFIERS",
    }
    assert "Maria" not in json.dumps(report) and "Gonzalez" not in json.dumps(report)
    assert before == {path.name: path.read_bytes() for path in run_dir.iterdir()}


def test_audit_clean_legacy_release_does_not_authorize_downstream(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    _approve(run_dir)
    transform_run(run_dir)
    _legacy_release(run_dir)
    report = audit_run(run_dir)
    assert report["status"] == "LEGACY_NO_NEW_FINDINGS"
    assert report["release_authorization"] is False
    with pytest.raises(IntegrityError, match="fresh scan"):
        transform_run(run_dir)


def test_audit_rejects_modified_source_without_emitting_text(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    (run_dir / "source.txt").write_text("Other identifying source content.")
    with pytest.raises(IntegrityError, match="protected-source binding") as error:
        audit_run(run_dir)
    assert "Other" not in str(error.value)


def test_current_pack_with_stale_environment_still_requires_rescan(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    detector = load_json(run_dir / "detection.json")["detector"]
    detector["threshold"] = 0.99
    _reseal(run_dir / "detection.json", {"detector": detector})
    report = audit_run(run_dir)
    assert report["status"] == "RESCAN_REQUIRED"
    assert report["risk_codes"] == ["DETECTOR_ENVIRONMENT_CHANGED"]


def test_audit_does_not_accept_bracketed_identifier_as_a_generated_surrogate(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "[Maria Gonzalez] agreed.")
    _approve(run_dir)
    transform_run(run_dir)
    _legacy_release(run_dir, leave_identifier=True)
    _reseal(run_dir / "second-pass.json", {"surrogate_ranges": [[0, len("[Maria Gonzalez]")]]})
    _reseal(
        run_dir / "privacy-release.json",
        {"second_pass_sha256": sha256_file(run_dir / "second-pass.json")},
    )
    with pytest.raises(IntegrityError, match="surrogate provenance"):
        audit_run(run_dir)


@pytest.mark.parametrize("leave_identifier", [False, True])
def test_authentic_v1_audit_without_surrogate_range_fields(
    tmp_path: Path, leave_identifier: bool,
) -> None:
    run_dir = _run(tmp_path, "[Maria Gonzalez] agreed." if leave_identifier else "Maria Gonzalez agreed.")
    _approve(run_dir)
    transform_run(run_dir)
    _legacy_release(run_dir, leave_identifier=leave_identifier, version="aegis-custom-strict-v1")
    second_path = run_dir / "second-pass.json"
    second = load_json(second_path)
    for key in ("integrity_sha256", "surrogate_ranges", "surrogate_exempt_finding_ids", "surrogate_exempt_count"):
        second.pop(key, None)
    second_path.write_bytes(canonical_bytes(seal(second)) + b"\n")
    _reseal(
        run_dir / "privacy-release.json", {"second_pass_sha256": sha256_file(second_path)},
    )
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    report = audit_run(run_dir)
    assert report["status"] == ("AFFECTED" if leave_identifier else "LEGACY_NO_NEW_FINDINGS")
    assert report["release_authorization"] is False
    assert before == {path.name: path.read_bytes() for path in run_dir.iterdir()}


def test_current_audit_requires_matching_config_policy_and_registration(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    _reseal(
        run_dir / "detection.json",
        {"config_sha256": "0" * 64, "policy_sha256": "0" * 64, "source_registration": {}},
    )
    report = audit_run(run_dir)
    assert report["status"] == "RESCAN_REQUIRED"
    assert report["risk_codes"] == [
        "CONFIGURATION_CHANGED", "POLICY_CHANGED", "SOURCE_REGISTRATION_CHANGED",
    ]


def test_v1_fragmented_review_is_affected_even_after_both_name_parts_were_replaced(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria\nGonzalez agreed.")
    _approve(run_dir)
    transform_run(run_dir)
    _legacy_release(run_dir, version="aegis-custom-strict-v1")
    old_findings = [
        {"finding_id": "F-0001", "entity_type": "PERSON", "start": 0, "end": 5,
         "score": 0.9, "recognizer": "legacy", "action": "REPLACE_AND_REVIEW",
         "value_sha256": sha256_bytes(b"Maria")},
        {"finding_id": "F-0002", "entity_type": "PERSON", "start": 6, "end": 14,
         "score": 0.9, "recognizer": "legacy", "action": "REPLACE_AND_REVIEW",
         "value_sha256": sha256_bytes(b"Gonzalez")},
    ]
    _reseal(run_dir / "detection-ledger.json", {"findings": old_findings})
    _reseal(
        run_dir / "detection.json",
        {"finding_count": 2, "ledger_sha256": sha256_file(run_dir / "detection-ledger.json")},
    )
    _reseal(
        run_dir / "review.json",
        {"decisions": [{"finding_id": item["finding_id"], "decision": "CONFIRMED"} for item in old_findings],
         "detection_sha256": sha256_file(run_dir / "detection.json"),
         "ledger_sha256": sha256_file(run_dir / "detection-ledger.json")},
    )
    (run_dir / "transformed.txt").write_text("[PERSON_001]\n[PERSON_002] agreed.")
    _reseal(run_dir / "second-pass.json", {"surrogate_ranges": None})
    _reseal(
        run_dir / "privacy-release.json",
        {"detection_sha256": sha256_file(run_dir / "detection.json"),
         "ledger_sha256": sha256_file(run_dir / "detection-ledger.json"),
         "review_sha256": sha256_file(run_dir / "review.json"),
         "second_pass_sha256": sha256_file(run_dir / "second-pass.json"),
         "transformed_sha256": sha256_file(run_dir / "transformed.txt")},
    )
    report = audit_run(run_dir)
    assert report["status"] == "AFFECTED"
    assert report["risk_codes"] == ["LEGACY_DETECTOR", "PERSON_MENTION_NOT_REVIEWED_AS_UNIT"]


def test_current_released_audit_revalidates_the_present_bundle_without_writes(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    _approve(run_dir)
    transform_run(run_dir)
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    report = audit_run(run_dir)
    assert report["status"] == "CURRENT"
    assert "revalidated release bundle" in report["notice"]
    assert report["release_authorization"] is False
    assert before == {path.name: path.read_bytes() for path in run_dir.iterdir()}
    assert "Maria" not in json.dumps(report) and str(run_dir) not in json.dumps(report)


@pytest.mark.parametrize("tamper", ["unsealed_release", "resealed_transformed_source"])
def test_current_release_tampering_blocks_audit_with_source_free_cli_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tamper: str,
) -> None:
    from aegisqda.cli import main

    run_dir = _run(tmp_path, "Maria Gonzalez agreed.")
    _approve(run_dir)
    transform_run(run_dir)
    if tamper == "unsealed_release":
        release_path = run_dir / "privacy-release.json"
        release = load_json(release_path)
        release["reviewer_id"] = "Maria Gonzalez"
        release_path.write_text(json.dumps(release))
    else:
        transformed = run_dir / "transformed.txt"
        transformed.write_text("[PERSON_001] invented output content.")
        _reseal(
            run_dir / "privacy-release.json", {"transformed_sha256": sha256_file(transformed)},
        )
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    with pytest.raises(IntegrityError, match="current-release bundle"):
        audit_run(run_dir)
    assert main(["audit", str(run_dir)]) == 2
    output = capsys.readouterr()
    assert "provenance revalidation" in output.err
    assert "Maria" not in output.out + output.err
    assert str(run_dir) not in output.out + output.err
    assert "invented output" not in output.out + output.err
    assert before == {path.name: path.read_bytes() for path in run_dir.iterdir()}

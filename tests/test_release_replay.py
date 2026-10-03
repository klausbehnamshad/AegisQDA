"""A valid signature cannot authorize a different, resealed transformation."""

from pathlib import Path

import pytest

from aegisqda.errors import DownstreamBlocked, ReviewRequired
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from aegisqda.privacy_gate import validate_release
from aegisqda.review_signature import create_review_key
from aegisqda.safeio import load_json
from aegisqda.workflow import scan_source, transform_run, write_review


def _reseal(path: Path, payload: dict) -> None:
    payload.pop("integrity_sha256", None)
    path.write_bytes(canonical_bytes(seal(payload)) + b"\n")


def test_signed_review_does_not_authorize_resealed_different_output(fixture_root: Path, tmp_path: Path) -> None:
    run = scan_source(fixture_root / "en/sample.srt", language="en", case_id="CASE-REPLAY", run_root=tmp_path / "runs", synthetic=True)
    key, _, _ = create_review_key(tmp_path / "review-key.pem")
    decisions = [{"finding_id": item["finding_id"], "decision": "CONFIRMED"} for item in load_json(run / "detection-ledger.json")["findings"]]
    write_review(run, "REVIEWER-001", decisions, signing_key=key)
    transform_run(run)
    validate_release(run)
    transformed = run / "transformed.srt"
    transformed.write_bytes(transformed.read_bytes().replace(b"[PERSON_001]", b"[PERSON_999]"))
    release = load_json(run / "privacy-release.json")
    release["transformed_sha256"] = sha256_file(transformed)
    _reseal(run / "privacy-release.json", release)
    with pytest.raises(DownstreamBlocked, match="policy-authorized"):
        validate_release(run)


def test_generalization_metadata_is_replayed(tmp_path: Path) -> None:
    source = tmp_path / "date.txt"
    source.write_text("The appointment was 17.07.2026.\n")
    run = scan_source(source, language="en", case_id="CASE-DATE-REPLAY", run_root=tmp_path / "runs", synthetic=True)
    ledger = load_json(run / "detection-ledger.json")
    write_review(run, "REVIEWER-001", [{"finding_id": f["finding_id"], "decision": "GENERALIZE_CONFIRMED"} for f in ledger["findings"]])
    transform_run(run)
    validate_release(run)
    second = load_json(run / "second-pass.json")
    assert second["generalizations"][0]["text"] == "[YEAR_2026]"
    second["generalizations"][0]["rule_id"] = "UNAPPROVED"
    _reseal(run / "second-pass.json", second)
    release = load_json(run / "privacy-release.json")
    release["second_pass_sha256"] = sha256_file(run / "second-pass.json")
    _reseal(run / "privacy-release.json", release)
    with pytest.raises(DownstreamBlocked):
        validate_release(run)


def test_unreviewed_occurrence_cannot_reuse_false_positive_exemption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from aegisqda.detection import Finding
    text = "Marker 17.07.2026 and appointment 17.07.2026.\n"
    value = "17.07.2026"
    first, second = text.index(value), text.rindex(value)
    def finding(start: int) -> Finding:
        return Finding("F-0001", "DATE_TIME", start, start + len(value), 0.9, "synthetic", "GENERALIZE_AND_REVIEW", sha256_bytes(value.encode()))
    responses = iter([[finding(first)], [finding(second)]])
    monkeypatch.setattr("aegisqda.workflow.scan_document", lambda *args: next(responses))
    source = tmp_path / "dates.txt"
    source.write_text(text)
    run = scan_source(source, language="en", case_id="CASE-FP-BOUND", run_root=tmp_path / "runs", synthetic=True)
    write_review(run, "REVIEWER-001", [{"finding_id": "F-0001", "decision": "FALSE_POSITIVE", "rationale": "This reviewed occurrence is an artificial marker."}])
    with pytest.raises(ReviewRequired, match="second-pass"):
        transform_run(run)


def test_french_generated_year_has_bound_ner_exemption(fixture_root: Path, tmp_path: Path) -> None:
    run = scan_source(fixture_root / "interviews/fr/expert_clean.srt", language="fr", case_id="CASE-FR-YEAR", run_root=tmp_path / "runs", synthetic=True)
    decisions = [{"finding_id": item["finding_id"], "decision": {"REPLACE_AND_REVIEW": "CONFIRMED", "GENERALIZE_AND_REVIEW": "GENERALIZE_CONFIRMED"}[item["action"]]} for item in load_json(run / "detection-ledger.json")["findings"]]
    write_review(run, "SYNTHETIC-REVIEWER", decisions)
    transform_run(run)
    validate_release(run)
    second = load_json(run / "second-pass.json")
    assert second["generalizations"][0]["text"] == "[YEAR_2026]"
    assert second["unresolved_count"] == 0

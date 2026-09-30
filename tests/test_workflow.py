from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from aegisqda.digqda_adapter import analyze_run
from aegisqda.errors import DownstreamBlocked, IntegrityError, ReviewRequired
from aegisqda.manifests import sha256_bytes
from aegisqda.privacy_gate import validate_release
from aegisqda.review_signature import create_review_key
from aegisqda.safeio import load_json
from aegisqda.workflow import interactive_review, scan_source, transform_run, write_review


def _approve_all(run_dir: Path, reviewer: str = "REVIEWER-001") -> None:
    ledger = load_json(run_dir / "detection-ledger.json")
    decisions = [
        {"finding_id": item["finding_id"], "decision": "CONFIRMED"}
        for item in ledger["findings"]
    ]
    write_review(run_dir, reviewer, decisions)


@pytest.mark.parametrize("language", ["de", "fr", "en"])
def test_synthetic_e2e_release(fixture_root: Path, tmp_path: Path, language: str) -> None:
    run_dir = scan_source(
        fixture_root / language / "sample.srt",
        language=language,
        case_id=f"CASE-{language.upper()}",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    _approve_all(run_dir)
    release_path = transform_run(run_dir)
    release = load_json(release_path)
    transformed = (run_dir / "transformed.srt").read_text(encoding="utf-8")
    original = (fixture_root / language / "sample.srt").read_text(encoding="utf-8")
    assert release["state"] == "PRIVACY_RELEASED"
    assert "guaranteed" not in release["release_claim"].casefold()
    assert "@example.com" not in transformed
    assert "[PERSON_001]" in transformed
    assert "[LOCATION_001]" in transformed
    assert transformed.count("\n") == original.count("\n")
    assert "00:00:01,000 --> 00:00:07,000" in transformed
    for path in (run_dir, run_dir / "detection.json", run_dir / "review.json"):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o700 if path.is_dir() else 0o600)


def test_scan_logs_and_manifests_do_not_contain_cleartext(fixture_root: Path, tmp_path: Path) -> None:
    run_dir = scan_source(
        fixture_root / "en" / "sample.srt",
        language="en",
        case_id="CASE-LEAK",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    for name in ("detection.json", "detection-ledger.json"):
        content = (run_dir / name).read_text(encoding="utf-8")
        assert "Jane Example" not in content
        assert "jane@example.com" not in content


def test_review_must_cover_every_finding(fixture_root: Path, tmp_path: Path) -> None:
    run_dir = scan_source(
        fixture_root / "en" / "sample.srt",
        language="en",
        case_id="CASE-REVIEW",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    with pytest.raises(ReviewRequired, match="every finding"):
        write_review(run_dir, "REVIEWER-001", [])


def test_transform_before_review_blocks(fixture_root: Path, tmp_path: Path) -> None:
    run_dir = scan_source(
        fixture_root / "de" / "sample.srt",
        language="de",
        case_id="CASE-EARLY",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    with pytest.raises(ReviewRequired):
        transform_run(run_dir)


def test_analyze_before_release_never_invokes_downstream(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = scan_source(
        fixture_root / "en" / "sample.srt",
        language="en",
        case_id="CASE-NO-DOWNSTREAM",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    invoked = False

    def forbidden(*args: object, **kwargs: object) -> object:
        nonlocal invoked
        invoked = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr("subprocess.run", forbidden)
    with pytest.raises(DownstreamBlocked):
        analyze_run(run_dir)
    assert invoked is False


def test_tampered_review_blocks(fixture_root: Path, tmp_path: Path) -> None:
    run_dir = scan_source(
        fixture_root / "fr" / "sample.srt",
        language="fr",
        case_id="CASE-TAMPER",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    _approve_all(run_dir)
    payload = json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    payload["reviewer_id"] = "ATTACKER-001"
    (run_dir / "review.json").write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(run_dir / "review.json", 0o600)
    with pytest.raises(IntegrityError, match="integrity"):
        transform_run(run_dir)


def test_repeated_entity_keeps_coreference(tmp_path: Path) -> None:
    source = tmp_path / "repeat.txt"
    source.write_text(
        "My name is Jane Example. Jane Example uses jane@example.com. Jane Example agreed.",
        encoding="utf-8",
    )
    run_dir = scan_source(
        source,
        language="en",
        case_id="CASE-COREF",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    ledger = load_json(run_dir / "detection-ledger.json")
    findings = ledger["findings"]
    jane_hash = sha256_bytes(b"Jane Example")
    existing = [item for item in findings if item["value_sha256"] == jane_hash]
    additions = []
    text = source.read_text(encoding="utf-8")
    starts = [index for index in range(len(text)) if text.startswith("Jane Example", index)]
    covered = {item["start"] for item in existing}
    for number, start in enumerate((item for item in starts if item not in covered), 1):
        additions.append(
            {
                "finding_id": f"A-{number:04d}",
                "entity_type": "PERSON",
                "start": start,
                "end": start + len("Jane Example"),
                    "value_sha256": jane_hash,
                    "action": "REPLACE_AND_REVIEW",
                    "decision": "CONFIRMED",
            }
        )
    decisions = [{"finding_id": item["finding_id"], "decision": "CONFIRMED"} for item in findings]
    write_review(run_dir, "REVIEWER-001", decisions, additions)
    transform_run(run_dir)
    transformed = (run_dir / "transformed.txt").read_text(encoding="utf-8")
    assert transformed.count("[PERSON_001]") == 3
    assert "Jane Example" not in transformed


def test_tampered_release_blocks_downstream(fixture_root: Path, tmp_path: Path) -> None:
    run_dir = scan_source(
        fixture_root / "en" / "sample.srt",
        language="en",
        case_id="CASE-RELEASE-TAMPER",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    _approve_all(run_dir)
    release_path = transform_run(run_dir)
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    payload["state"] = "PRIVACY_RELEASED_TAMPERED"
    release_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(release_path, 0o600)
    with pytest.raises(DownstreamBlocked):
        validate_release(run_dir)


def test_tampered_second_pass_blocks_downstream(fixture_root: Path, tmp_path: Path) -> None:
    run_dir = scan_source(
        fixture_root / "en" / "sample.srt",
        language="en",
        case_id="CASE-SECOND-TAMPER",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    _approve_all(run_dir)
    transform_run(run_dir)
    second = run_dir / "second-pass.json"
    payload = json.loads(second.read_text(encoding="utf-8"))
    payload["unresolved_count"] = 1
    second.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(second, 0o600)
    with pytest.raises(DownstreamBlocked):
        validate_release(run_dir)


def test_generalize_action_requires_explicit_resolution(tmp_path: Path) -> None:
    source = tmp_path / "date.txt"
    source.write_text("The appointment was 17.07.2026.", encoding="utf-8")
    run_dir = scan_source(
        source,
        language="en",
        case_id="CASE-DATE",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    finding = load_json(run_dir / "detection-ledger.json")["findings"][0]
    with pytest.raises(ReviewRequired):
        write_review(
            run_dir,
            "REVIEWER-001",
            [{"finding_id": finding["finding_id"], "decision": "CONFIRMED"}],
        )
    write_review(
        run_dir,
        "REVIEWER-001",
        [{"finding_id": finding["finding_id"], "decision": "GENERALIZE_CONFIRMED"}],
    )
    transform_run(run_dir)
    assert "[DATE_TIME_GENERALIZED_001]" in (run_dir / "transformed.txt").read_text()


def test_block_action_cannot_be_confirmed(tmp_path: Path) -> None:
    source = tmp_path / "rare.txt"
    source.write_text("She is the only survivor.", encoding="utf-8")
    run_dir = scan_source(
        source,
        language="en",
        case_id="CASE-BLOCK",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    finding = load_json(run_dir / "detection-ledger.json")["findings"][0]
    with pytest.raises(ReviewRequired):
        write_review(
            run_dir,
            "REVIEWER-001",
            [{"finding_id": finding["finding_id"], "decision": "CONFIRMED"}],
        )


def test_false_positive_requires_rationale(tmp_path: Path) -> None:
    source = tmp_path / "date.txt"
    source.write_text("The code was 17.07.2026.", encoding="utf-8")
    run_dir = scan_source(
        source,
        language="en",
        case_id="CASE-RATIONALE",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    finding = load_json(run_dir / "detection-ledger.json")["findings"][0]
    with pytest.raises(ReviewRequired, match="rationale"):
        write_review(
            run_dir,
            "REVIEWER-001",
            [{"finding_id": finding["finding_id"], "decision": "FALSE_POSITIVE"}],
        )


def test_signed_review_is_verified(fixture_root: Path, tmp_path: Path) -> None:
    key, _, _ = create_review_key(tmp_path / "review-key.pem")
    run_dir = scan_source(
        fixture_root / "en" / "sample.srt",
        language="en",
        case_id="CASE-SIGNED",
        run_root=tmp_path / "runs",
        synthetic=True,
    )
    ledger = load_json(run_dir / "detection-ledger.json")
    decisions = [
        {"finding_id": item["finding_id"], "decision": "CONFIRMED"}
        for item in ledger["findings"]
    ]
    write_review(run_dir, "REVIEWER-001", decisions, signing_key=key)
    transform_run(run_dir)
    _, release = validate_release(run_dir)
    assert release["review_assurance"] == "SELF_SIGNED_LOCAL"


def _scripted_review(
    monkeypatch: pytest.MonkeyPatch, replies: dict[str, list[str]]
) -> list[str]:
    """Answer review prompts by prefix; each prefix pops its replies in order."""
    asked: list[str] = []

    def answer(prompt: str = "") -> str:
        asked.append(prompt)
        if prompt.startswith("confirm replacement"):
            return "c"
        if prompt.startswith("confirm generalization"):
            return "g"
        if prompt.startswith("false positive [f]"):
            return "f"
        if prompt.startswith("false-positive rationale"):
            return "synthetic fixture wording"
        for prefix, queue in replies.items():
            if prompt.startswith(prefix):
                if not queue:
                    raise EOFError
                return queue.pop(0)
        raise EOFError

    monkeypatch.setattr("builtins.input", answer)
    return asked


def _nickname_run(tmp_path: Path, case_id: str) -> Path:
    source = tmp_path / "nickname.txt"
    source.write_text(
        "Contact person@invalid.example today.\nEveryone calls her zebrafinch.\n"
        "Later zebrafinch agreed.\n",
        encoding="utf-8",
    )
    return scan_source(
        source, language="en", case_id=case_id, run_root=tmp_path / "runs", synthetic=True
    )


def test_review_end_of_input_aborts_without_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _nickname_run(tmp_path, "CASE-EOF")
    _scripted_review(monkeypatch, {})
    with pytest.raises(ReviewRequired, match="aborted"):
        interactive_review(run_dir, "REVIEWER-001")
    assert not (run_dir / "review.json").exists()


def test_review_adds_missed_text_and_reprompts_unknown_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _nickname_run(tmp_path, "CASE-ADD-TEXT")
    asked = _scripted_review(
        monkeypatch,
        {
            "add a missed detection": ["y", "y", "n"],
            "exact missed text": ["zebrafinch", "person@invalid.example"],
            "entity type": ["PERSN", "PERSON", "EMAIL_ADDRESS"],
        },
    )
    interactive_review(run_dir, "REVIEWER-001")
    assert sum(prompt.startswith("entity type") for prompt in asked) == 3
    review = load_json(run_dir / "review.json")
    text = (run_dir / "source.txt").read_text(encoding="utf-8")
    added = [text[item["start"]:item["end"]] for item in review["additions"]]
    assert "person@invalid.example" not in added  # already a confirmed finding
    transform_run(run_dir)
    transformed = (run_dir / "transformed.txt").read_text(encoding="utf-8")
    assert "zebrafinch" not in transformed
    assert "person@invalid.example" not in transformed


def test_review_missed_blocking_type_still_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _nickname_run(tmp_path, "CASE-ADD-BLOCK")
    _scripted_review(
        monkeypatch,
        {
            "add a missed detection": ["y"],
            "exact missed text": ["zebrafinch"],
            "entity type": ["KINSHIP"],
        },
    )
    with pytest.raises(ReviewRequired, match="blocking"):
        interactive_review(run_dir, "REVIEWER-001")
    assert not (run_dir / "review.json").exists()

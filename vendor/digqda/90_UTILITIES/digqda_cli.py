#!/usr/bin/env python3
"""Smooth, fail-closed orchestration for DigQDA's local method pipeline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from digqda_errors import WorkflowError
from qda_scope import apply_role_scope

ROOT = Path(__file__).resolve().parent.parent
UTIL = ROOT / "90_UTILITIES"
SCHEMA = ROOT / "10_GENERIC" / "p1_schema.json"
PROMPT_PATH = ROOT / "10_GENERIC" / "p1_prompt.txt"
P0_SCHEMA_PATH = ROOT / "schemas" / "p0_units.schema.json"
SYNTHETIC_ROOT = UTIL / "smoke" / "fixtures"
DEFAULT_OUT_ROOT = Path.home() / "DigQDA-Pilot"
OPAQUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SHA_RE = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
CLOUD_MARKERS = (
    "mobile documents",
    "com~apple~clouddocs",
    "dropbox",
    "onedrive",
    "google drive",
)

runner = None
validator = None
if importlib.util.find_spec("jsonschema") is not None:
    import qda_run_p1 as runner
if importlib.util.find_spec("rapidfuzz") is not None:
    import qda_validate as validator


def _require_runtime() -> None:
    missing = [name for name in ("jsonschema", "rapidfuzz")
               if importlib.util.find_spec(name) is None]
    if missing or runner is None or validator is None:
        names = ", ".join(missing or ["DigQDA-Laufzeitmodule"])
        raise WorkflowError(
            f"Python-Abhaengigkeiten fehlen ({names}). Installiere: "
            f"{sys.executable} -m pip install -r {ROOT / 'requirements.txt'}"
        )


def _readiness_problems(model: str, *, include_model: bool) -> list[str]:
    problems: list[str] = []
    required_modules = ["jsonschema", "rapidfuzz"]
    if include_model:
        required_modules.append("ollama")
    for module in required_modules:
        if importlib.util.find_spec(module) is None:
            problems.append(f"Python-Modul fehlt: {module}")
    for path in (SCHEMA, PROMPT_PATH, P0_SCHEMA_PATH):
        if not path.is_file():
            problems.append(f"Contract-Datei fehlt: {path}")
    if not include_model:
        return problems
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        problems.append("Ollama fehlt auf PATH")
        return problems
    probe = subprocess.run([ollama_bin, "list"], capture_output=True, text=True)
    if probe.returncode:
        problems.append("Ollama ist nicht erreichbar (starte: ollama serve)")
        return problems
    installed = [line.split()[0] for line in probe.stdout.splitlines()[1:] if line.split()]
    if model not in installed:
        problems.append(f"Modell nicht exakt installiert: {model}")
    return problems


def _inside(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(parent))) == str(parent)
    except ValueError:
        return False


def _resolved(path: Path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def _is_cloud_path(path: Path) -> bool:
    folded = str(path).casefold()
    return any(marker in folded for marker in CLOUD_MARKERS)


def _secure_dir(path: Path, *, create: bool = True) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise WorkflowError(f"Kein sicherer lokaler Ordner: {path}")
    path.chmod(0o700)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise WorkflowError(f"Ordnerrechte konnten nicht auf 0700 gesetzt werden: {path}")


def _secure_artifacts(run_dir: Path) -> None:
    for path in run_dir.rglob("*"):
        if path.is_symlink():
            raise WorkflowError(f"Unerwarteter Symlink im Laufordner: {path.name}")
        path.chmod(0o700 if path.is_dir() else 0o600)


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"{label} fehlt oder ist ungueltig: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"{label} muss ein JSON-Objekt sein")
    return value


def _sha_ok(value: object) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def evaluate_gate(
    segments: dict,
    coding: dict,
    validation: dict,
    *,
    runner_exit: int,
    validator_exit: int,
    requested_model: str,
    requested_mode: str,
    research_question: str,
    codebook_bytes: bytes | None,
    dry_run: bool,
) -> tuple[bool, list[str]]:
    """Evaluate the complete technical acceptance edge without soft fallbacks."""
    _require_runtime()
    reasons: list[str] = []
    meta = segments.get("meta") if isinstance(segments.get("meta"), dict) else {}
    units = segments.get("source_units") if isinstance(segments.get("source_units"), list) else []
    manifest = coding.get("_qda_run") if isinstance(coding.get("_qda_run"), dict) else {}
    results = coding.get("results") if isinstance(coding.get("results"), list) else []
    vman = validation.get("_qda_validation") if isinstance(validation.get("_qda_validation"), dict) else {}
    vresult = vman.get("result") if isinstance(vman.get("result"), dict) else {}
    statuses = manifest.get("statuses") if isinstance(manifest.get("statuses"), list) else []

    def require(condition: bool, message: str) -> None:
        if not condition:
            reasons.append(message)

    unit_ids = [unit.get("unit_id") for unit in units if isinstance(unit, dict)]
    status_ids = [status.get("unit_id") for status in statuses if isinstance(status, dict)]
    result_ids = [result.get("unit_id") for result in results if isinstance(result, dict)]
    n_units = len(unit_ids)
    source_sha = meta.get("source_sha256")
    try:
        full_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
        schema_sha = hashlib.sha256(
            json.dumps(full_schema, sort_keys=True).encode()
        ).hexdigest()
        prompt_sha = hashlib.sha256(prompt_text.encode()).hexdigest()
        claim = runner.ALLOWED_METHOD_CLAIM[runner.PROMPT_ID]
        contract_sha = hashlib.sha256(json.dumps(
            {
                "prompt_id": runner.PROMPT_ID,
                "prompt_version": runner.PROMPT_VERSION,
                "schema_sha256": schema_sha,
                "prompt_sha256": prompt_sha,
                "method_claim": claim,
            },
            sort_keys=True,
        ).encode()).hexdigest()
        labels = None
        if codebook_bytes is not None:
            labels, _ = runner.parse_codebook(codebook_bytes.decode("utf-8"))
        grammar_sha = runner.canonical_json_sha256(
            runner.grammar_schema_for_mode(full_schema, requested_mode, labels)
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, runner.ContractInputError) as exc:
        raise WorkflowError(f"Lokale Contract-Artefakte sind nicht pruefbar: {exc}") from exc

    require(n_units > 0 and len(unit_ids) == len(units), "P0 enthaelt keine vollstaendigen Units")
    require(len(set(unit_ids)) == n_units, "P0-unit_id ist nicht eindeutig")
    require(manifest.get("n_units") == n_units, "Runner-Unitzahl weicht von P0 ab")
    require(manifest.get("n_ok") == n_units, "Nicht alle Units sind erfolgreich")
    require(len(statuses) == n_units and status_ids == unit_ids, "Runner-Statusbindung ist unvollstaendig")
    require(_sha_ok(source_sha), "P0-Quellenhash fehlt")
    require(manifest.get("source_sha256") == source_sha, "Runner ist an eine andere Quelle gebunden")
    require(vman.get("source_sha256") == source_sha, "Validator ist an eine andere Quelle gebunden")
    if meta.get("scope_applied"):
        require(_sha_ok(meta.get("scope_sha256")), "P0-Scope-Hash fehlt")
        require(manifest.get("scope_sha256") == meta.get("scope_sha256"),
                "Runner ist nicht an den P0-Rollen-Scope gebunden")
    require(manifest.get("library_version") == runner.LIBRARY_VERSION, "Library-Version ist unerwartet")
    require(manifest.get("contract_version") == runner.CONTRACT_VERSION, "Contract-Version ist unerwartet")
    require(manifest.get("prompt_id") == runner.PROMPT_ID, "Prompt-ID ist unerwartet")
    require(manifest.get("prompt_version") == runner.PROMPT_VERSION, "Prompt-Version ist unerwartet")
    require(manifest.get("prompt_source") == "file", "Prompt stammt nicht aus der kanonischen Datei")
    require(
        manifest.get("allowed_method_claim") == runner.ALLOWED_METHOD_CLAIM[runner.PROMPT_ID],
        "Methodenclaim ist nicht vertraglich gebunden",
    )
    require(manifest.get("backend") == "ollama", "Backendbindung fehlt")
    require(manifest.get("model") == requested_model, "Modellbindung weicht vom Aufruf ab")
    require(manifest.get("mode") == requested_mode, "Methodenmodus weicht vom Aufruf ab")
    require(vman.get("validator_version") == validator.VALIDATOR_VERSION, "Validator-Version ist unerwartet")
    require(re.fullmatch(r"[0-9a-f]{32}", str(manifest.get("run_id", ""))) is not None,
            "run_id fehlt oder ist ungueltig")
    for key in (
        "contract_sha256", "prompt_sha256", "schema_sha256", "grammar_sha256",
        "research_question_sha256",
    ):
        require(_sha_ok(manifest.get(key)), f"{key} fehlt oder ist ungueltig")
    require(manifest.get("prompt_sha256") == prompt_sha, "Prompt-Hash weicht von der kanonischen Datei ab")
    require(manifest.get("schema_sha256") == schema_sha, "Schema-Hash weicht von der kanonischen Datei ab")
    require(manifest.get("contract_sha256") == contract_sha, "Contract-Hash ist nicht reproduzierbar")
    require(manifest.get("grammar_sha256") == grammar_sha, "Modus-Grammatik ist nicht reproduzierbar")
    effective_rq = research_question or "explorative Analyse"
    require(manifest.get("research_question_sha256") == runner.sha256_text(effective_rq),
            "Forschungsfragen-Hash weicht vom Aufruf ab")
    if requested_mode == "OPEN_DESCRIPTIVE":
        require(manifest.get("codebook_sha256") is None and manifest.get("codebook_size") == 0,
                "OPEN-Lauf darf kein Codebuch binden")
    else:
        expected_codebook_sha = hashlib.sha256(codebook_bytes or b"").hexdigest()
        require(manifest.get("codebook_sha256") == expected_codebook_sha
                and manifest.get("codebook_size") == len(labels or []),
                "Codebuchmodus ist nicht an ein nicht-leeres Codebuch gebunden")
    for pos, status in enumerate(statuses):
        if not isinstance(status, dict):
            reasons.append("Runner-Status ist kein Objekt")
            continue
        require(_sha_ok(status.get("unit_input_sha256")), "Unit-Input-Hash fehlt")
        require(_sha_ok(status.get("rendered_prompt_sha256")), "Gerenderter Prompt-Hash fehlt")
        if pos < len(units):
            require(status.get("unit_input_sha256") == runner.canonical_json_sha256(units[pos]),
                    "Unit-Input-Hash ist nicht reproduzierbar")
    require(vman.get("input_sha256") == runner.canonical_json_sha256(coding),
            "Validierungs-Envelope ist nicht exakt an dieses P1-Ergebnis gebunden")

    if dry_run:
        require(runner_exit == 0, "Dry-run Runner ist fehlgeschlagen")
        require(all(s.get("status") == "DRY_RUN_OK" for s in statuses), "Dry-run ist nicht durchgaengig bereit")
        require(manifest.get("provenance_level") == "DRY_RUN", "Dry-run Provenance ist falsch")
        require(manifest.get("model_digest") is None, "Dry-run darf keinen Modelldigest vortaeuschen")
        require(not results, "Dry-run darf keine Modellresultate vortaeuschen")
        require(validator_exit == 2, "Dry-run Validator muss das leere Nicht-Ergebnis abweisen")
        require(vresult.get("verdict") == "INVALID_INPUT", "Dry-run Validatorverdikt ist unerwartet")
    else:
        require(runner_exit == 0, "Runner ist fehlgeschlagen")
        require(validator_exit == 0, "Validator ist nicht PASS")
        require(all(s.get("status") == "OK" for s in statuses), "Mindestens eine Unit ist nicht OK")
        require(manifest.get("provenance_level") == "MODEL_BOUND", "Modellprovenance ist nicht gebunden")
        require(_sha_ok(manifest.get("model_digest")), "Konkreter Modelldigest fehlt")
        require(isinstance(manifest.get("backend_client_version"), str)
                and bool(manifest.get("backend_client_version")),
                "Backend-Client-Version fehlt")
        require(result_ids == unit_ids, "Resultate sind nicht exakt an alle P0-Units gebunden")
        require(vresult.get("verdict") == "PASS", "Externe Evidenzvalidierung ist nicht PASS")
    return not reasons, reasons


def _run(command: list[str], log_lines: list[str]) -> int:
    proc = subprocess.run(command, capture_output=True, text=True)
    log_lines.append(f"$ {Path(command[1]).name if len(command) > 1 else command[0]} [exit {proc.returncode}]")
    return proc.returncode


def doctor(model: str) -> int:
    problems = _readiness_problems(model, include_model=True)
    if problems:
        print("DigQDA ist noch nicht pilotbereit:")
        for problem in problems:
            print(f"  - {problem}")
        if any("Python-Modul" in problem for problem in problems):
            print(f"\nInstallieren: {sys.executable} -m pip install -r {ROOT / 'requirements.txt'}")
        return 1
    print(f"DigQDA ist pilotbereit. Modell: {model}")
    return 0


def _validate_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    if not OPAQUE_RE.fullmatch(args.opaque_id):
        raise WorkflowError("Fall-ID muss opak und pfadsicher sein: Buchstaben, Ziffern, . _ -")
    source = _resolved(Path(args.source))
    if not source.is_file() or source.suffix.lower() not in {".srt", ".txt"}:
        raise WorkflowError("Quelle muss eine lesbare lokale .srt- oder .txt-Datei sein")
    out_root = _resolved(Path(args.out_root))
    codebook = _resolved(Path(args.codebook)) if args.codebook else None
    if _inside(out_root, ROOT):
        raise WorkflowError("Der Laufordner muss ausserhalb des Git-Repos liegen")
    if _is_cloud_path(source) or _is_cloud_path(out_root) or (codebook and _is_cloud_path(codebook)):
        raise WorkflowError("Quelle, Codebuch und Laufordner duerfen nicht in einem Cloud-Sync-Pfad liegen")
    if _inside(source, ROOT):
        if not args.synthetic or not _inside(source, _resolved(SYNTHETIC_ROOT)):
            raise WorkflowError("Echte Quellen duerfen nicht im Git-Repo liegen")
    elif args.synthetic:
        raise WorkflowError("--synthetic ist ausschliesslich fuer die gebuendelten Testdaten")
    if args.mode != "OPEN_DESCRIPTIVE":
        if not codebook or not codebook.is_file():
            raise WorkflowError(f"{args.mode} braucht --codebook mit einer lokalen JSON-Datei")
    elif codebook:
        raise WorkflowError("OPEN_DESCRIPTIVE verwendet kein Codebuch; --codebook bitte entfernen")
    return source, out_root, codebook


def _load_role_scope(args: argparse.Namespace) -> tuple[dict[str, str] | None, list[str]]:
    if bool(args.role_map) != bool(args.include_role):
        raise WorkflowError("--role-map und mindestens ein --include-role gehoeren zusammen")
    if not args.role_map:
        return None, []
    path = _resolved(Path(args.role_map))
    if not path.is_file() or _is_cloud_path(path):
        raise WorkflowError("Rollenmap muss eine lokale JSON-Datei ausserhalb von Cloud-Sync sein")
    data = _load_json(path, "Rollenmap")
    if not data or not all(
        isinstance(key, str) and key.strip()
        and isinstance(value, str) and value.strip()
        for key, value in data.items()
    ):
        raise WorkflowError("Rollenmap muss nicht-leere Sprecherlabels auf nicht-leere Rollen abbilden")
    included = list(dict.fromkeys(args.include_role))
    unknown_roles = sorted(set(included) - set(data.values()))
    if unknown_roles:
        raise WorkflowError("--include-role fehlt in der Rollenmap: " + ", ".join(unknown_roles))
    return data, included


def pilot(args: argparse.Namespace) -> int:
    _require_runtime()
    problems = _readiness_problems(args.model, include_model=not args.dry_run)
    if problems:
        raise WorkflowError("Pilot nicht bereit: " + "; ".join(problems))
    source, out_root, codebook = _validate_inputs(args)
    role_map, included_roles = _load_role_scope(args)
    old_umask = os.umask(0o077)
    try:
        _secure_dir(out_root)
        case_dir = out_root / args.opaque_id
        _secure_dir(case_dir)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_dir = case_dir / stamp
        run_dir.mkdir(mode=0o700, exist_ok=False)
        label = f"{args.opaque_id}{source.suffix.lower()}"
        segments_path = run_dir / "segments.json"
        segments_full_path = run_dir / "segments_full.json"
        coding_path = run_dir / "coding.json"
        validation_path = run_dir / "validation.json"
        report_path = run_dir / "validation.md"
        review_path = run_dir / "REVIEW.md"
        log_path = run_dir / "run.log"
        log_lines = [
            f"DigQDA pilot {stamp}",
            f"case_id={args.opaque_id}",
            f"mode={args.mode}",
            f"model={args.model}",
            f"dry_run={str(args.dry_run).lower()}",
        ]

        segment_cmd = [
            sys.executable, str(UTIL / "qda_segment.py"), "--source", str(source),
            "--source-label", label, "--out", str(segments_path),
        ]
        if role_map and source.suffix.lower() == ".srt":
            segment_cmd.extend(("--mode", "cue"))
        segment_exit = _run(segment_cmd, log_lines)
        if segment_exit or not segments_path.is_file():
            log_lines.extend(("technical_gate=BLOCKED", "gate_reason=P0-Segmentierung fehlgeschlagen"))
            log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
            _secure_artifacts(run_dir)
            raise WorkflowError("P0-Segmentierung ist fehlgeschlagen")

        excluded_units: list[str] = []
        if role_map:
            full_segments = _load_json(segments_path, "P0-Envelope")
            scoped_segments, excluded_units = apply_role_scope(
                full_segments, role_map, included_roles
            )
            segments_full_path.write_bytes(segments_path.read_bytes())
            runner.atomic_write(
                str(segments_path),
                json.dumps(scoped_segments, ensure_ascii=False, indent=2),
            )
            log_lines.extend((
                "scope_applied=true",
                f"scope_sha256={scoped_segments['meta']['scope_sha256']}",
                f"scope_included_roles={','.join(included_roles)}",
                f"scope_excluded_n_units={len(excluded_units)}",
            ))

        runner_cmd = [
            sys.executable, str(UTIL / "qda_run_p1.py"), "--units", str(segments_path),
            "--schema", str(SCHEMA), "--model", args.model, "--mode", args.mode,
            "--out", str(coding_path),
        ]
        if args.research_question:
            runner_cmd.extend(("--research-question", args.research_question))
        if codebook:
            runner_cmd.extend(("--codebook", str(codebook)))
        if args.dry_run:
            runner_cmd.append("--dry-run")
        if args.diagnostic_quarantine:
            runner_cmd.extend(("--quarantine-dir", str(run_dir / "quarantine")))
        runner_exit = _run(runner_cmd, log_lines)
        if not coding_path.is_file():
            log_lines.extend(("technical_gate=BLOCKED", "gate_reason=P1 ohne Ergebnis-Envelope"))
            log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
            _secure_artifacts(run_dir)
            raise WorkflowError("P1 hat kein pruefbares Ergebnis-Envelope geschrieben")

        validate_cmd = [
            sys.executable, str(UTIL / "qda_validate.py"), "--source", str(source),
            "--source-label", label, "--json", str(coding_path),
            "--out", str(validation_path), "--report", str(report_path),
        ]
        validator_exit = _run(validate_cmd, log_lines)
        segments = _load_json(segments_path, "P0-Envelope")
        coding = _load_json(coding_path, "P1-Envelope")
        validation = _load_json(validation_path, "Validierungs-Envelope")
        passed, reasons = evaluate_gate(
            segments, coding, validation,
            runner_exit=runner_exit,
            validator_exit=validator_exit,
            requested_model=args.model,
            requested_mode=args.mode,
            research_question=args.research_question,
            codebook_bytes=codebook.read_bytes() if codebook else None,
            dry_run=args.dry_run,
        )
        manifest = coding["_qda_run"]
        verdict = validation["_qda_validation"]["result"]["verdict"]
        log_lines.extend((
            f"technical_gate={'READY' if passed else 'BLOCKED'}",
            f"runner_exit={runner_exit}",
            f"validator_exit={validator_exit}",
            f"validator_verdict={verdict}",
            f"n_ok={manifest.get('n_ok')}/{manifest.get('n_units')}",
            f"run_id={manifest.get('run_id')}",
            f"model_digest={manifest.get('model_digest')}",
            f"grammar_sha256={manifest.get('grammar_sha256')}",
        ))
        if reasons:
            log_lines.extend(f"gate_reason={reason}" for reason in reasons)
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        review_path.write_text(
            "# DigQDA — methodische Freigabe\n\n"
            f"- Fall-ID: `{args.opaque_id}`\n"
            f"- Technisches Gate: **{'BEREIT' if passed else 'GESPERRT'}**\n"
            f"- Validierung: **{verdict}**\n"
            f"- Rollen-Scope: **{'aktiv' if role_map else 'nicht gesetzt'}**"
            f"{f' ({len(excluded_units)} Unit(s) ausgeschlossen)' if role_map else ''}\n"
            f"- Detailreport: [validation.md](validation.md)\n\n"
            "## Manuelle Quellenpruefung\n\n"
            "- [ ] Alle gebundenen Zitate wurden gegen die lokale Quelle geprueft.\n"
            "- [ ] Codes und Definitionen wurden methodisch geprueft.\n"
            "- [ ] Unsicherheiten und Grenzfaelle wurden dokumentiert.\n\n"
            "Reviewer: ____________________  Datum: __________\n\n"
            "Entscheidung: [ ] annehmen  [ ] ueberarbeiten  [ ] verwerfen\n",
            encoding="utf-8",
        )
        _secure_artifacts(run_dir)
        if passed:
            state = "Plumbing bereit" if args.dry_run else "Technisch bestanden"
            print(f"{state}: {args.opaque_id}")
            print(f"Methodische Pruefung: {review_path}")
            print(f"Laufordner: {run_dir}")
            return 0
        print(f"Pilot gesperrt: {args.opaque_id}", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        print(f"Diagnose: {report_path}", file=sys.stderr)
        return 1
    finally:
        os.umask(old_umask)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="digqda", description="Lokale, evidenzgebundene QDA-Pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor", help="Lokale Pilotbereitschaft pruefen")
    doctor_parser.add_argument("--model", default="gemma4:e4b")
    pilot_parser = sub.add_parser("pilot", help="Einen isolierten, ueberwachten Methodenlauf starten")
    pilot_parser.add_argument("opaque_id", help="Opake Fall-ID, z. B. CASE-001")
    pilot_parser.add_argument("source", help="Lokale .srt- oder .txt-Quelle")
    pilot_parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    pilot_parser.add_argument("--model", default="gemma4:e4b")
    def mode_value(value: str) -> str:
        aliases = {
            "open": "OPEN_DESCRIPTIVE",
            "strict": "STRICT_CODEBOOK",
            "constrained": "CONSTRAINED_EXTENSION",
            "open_descriptive": "OPEN_DESCRIPTIVE",
            "strict_codebook": "STRICT_CODEBOOK",
            "constrained_extension": "CONSTRAINED_EXTENSION",
        }
        try:
            return aliases[value.casefold()]
        except KeyError as exc:
            raise argparse.ArgumentTypeError("erlaubt: open, strict, constrained") from exc

    pilot_parser.add_argument(
        "--mode", default="OPEN_DESCRIPTIVE", type=mode_value,
        metavar="{open,strict,constrained}",
    )
    pilot_parser.add_argument("--codebook")
    pilot_parser.add_argument("--research-question", default="")
    pilot_parser.add_argument(
        "--role-map",
        help="JSON-Objekt: explizites Sprecherlabel -> methodische Rolle",
    )
    pilot_parser.add_argument(
        "--include-role", action="append",
        help="Nur diese Rolle an P1 senden (wiederholbar; erfordert --role-map)",
    )
    pilot_parser.add_argument("--dry-run", action="store_true", help="Pipeline ohne Modellantwort pruefen")
    pilot_parser.add_argument("--synthetic", action="store_true", help="Nur fuer gebuendelte Testfixture")
    pilot_parser.add_argument("--diagnostic-quarantine", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.model)
        return pilot(args)
    except WorkflowError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

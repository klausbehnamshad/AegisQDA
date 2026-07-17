#!/usr/bin/env bash
# =============================================================================
# DigQDA — end-to-end smoke test (synthetic data, real local Gemma via Ollama)
# =============================================================================
# Exercises P0 (SRT + TXT), then P1 + validation (SRT) in OPEN and STRICT mode.
# The script intentionally keeps running after a scenario finding so both modes
# are diagnosed, then returns a fail-closed aggregate exit code.
#
#   Real model:  MODEL=gemma4:e4b bash 90_UTILITIES/smoke/run_smoke.sh
#   Plumbing:    DRY=1 bash 90_UTILITIES/smoke/run_smoke.sh
#
# Environment:
#   MODEL   exact installed Ollama tag (default: gemma4:e4b)
#   PYTHON  Python interpreter path (default: python3)
#   DRY     1 = exercise plumbing without calling a model
#   OUT     artifact directory (default: 90_UTILITIES/smoke/out)
# =============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
UTIL="$REPO/90_UTILITIES"
SCHEMA="$REPO/10_GENERIC/p1_schema.json"
SRT="$HERE/fixtures/interview_demo.srt"
TXT="$HERE/fixtures/interview_demo.txt"
CB="$HERE/fixtures/codebook_demo.json"
OUT="${OUT:-$HERE/out}"
MODEL="${MODEL:-gemma4:e4b}"
PY="${PYTHON:-python3}"
DRY="${DRY:-0}"
SUM="$OUT/SMOKE_SUMMARY.txt"
RUN_FAILURES=0

mkdir -p "$OUT"

# Remove only artifacts owned by this synthetic harness. This prevents a failed
# invocation from validating output left by an earlier run.
rm -f -- \
  "$OUT/SMOKE_SUMMARY.txt" \
  "$OUT/segments_srt.json" \
  "$OUT/segments_txt.json" \
  "$OUT/p1_open.json" \
  "$OUT/p1_strict.json" \
  "$OUT/validation_open.json" \
  "$OUT/validation_open.md" \
  "$OUT/validation_strict.json" \
  "$OUT/validation_strict.md"
rm -rf -- "$OUT/quarantine"
: > "$SUM"

log() {
  printf '%s\n' "$*" | tee -a "$SUM"
}

run_logged() {
  "$@" 2>&1 | tee -a "$SUM"
  local rc=${PIPESTATUS[0]}
  return "$rc"
}

run_artifact_command() {
  # These CLIs emit their full JSON/Markdown artifact on stdout even when an
  # output path is supplied. Keep the terminal concise while preserving stderr.
  # A regular file is used instead of process substitution for macOS Bash 3.2
  # and restricted environments where /dev/fd cannot be opened.
  local stderr_file="$OUT/.command_stderr"
  local rc
  : > "$stderr_file"
  "$@" >/dev/null 2>"$stderr_file"
  rc=$?
  if [ -s "$stderr_file" ]; then
    tee -a "$SUM" < "$stderr_file" >&2
  fi
  rm -f -- "$stderr_file"
  return "$rc"
}

log "==================================================================="
log " DigQDA smoke test   model=$MODEL   dry=$DRY"
log " $("$PY" -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))')"
log "==================================================================="

# ---------- preflight ----------
log ""
log "[preflight] Python dependencies"
if ! "$PY" -c "import jsonschema, rapidfuzz" 2>/dev/null; then
  log "  MISSING jsonschema/rapidfuzz"
  log "  FIX: $PY -m pip install -r \"$REPO/requirements.txt\""
  exit 10
fi
log "  ok: jsonschema, rapidfuzz"

if [ "$DRY" != "1" ]; then
  log "[preflight] Ollama server, model and Python client"
  if ! command -v ollama >/dev/null 2>&1; then
    log "  ERROR: 'ollama' is not on PATH. Install/start Ollama first."
    exit 11
  fi
  if ! OLLAMA_LIST="$(ollama list 2>&1)"; then
    log "  ERROR: 'ollama list' failed. Start the Ollama app or run 'ollama serve'."
    log "  DETAIL: $OLLAMA_LIST"
    exit 12
  fi
  if ! printf '%s\n' "$OLLAMA_LIST" | awk 'NR > 1 {print $1}' | grep -Fqx -- "$MODEL"; then
    log "  ERROR: model '$MODEL' is not installed. Installed models:"
    printf '%s\n' "$OLLAMA_LIST" | sed 's/^/           /' | tee -a "$SUM"
    log "  FIX: ollama pull $MODEL"
    log "       or rerun with MODEL=<exact-tag-from-ollama-list>"
    exit 13
  fi
  if ! "$PY" -c "import ollama" 2>/dev/null; then
    log "  MISSING Python 'ollama' client"
    log "  FIX: $PY -m pip install -r \"$REPO/requirements.txt\""
    exit 14
  fi
  log "  ok: server up, model '$MODEL' present, Python client present"
fi

# ---------- P0 segmentation ----------
segment_source() {
  local kind="$1"
  local source="$2"
  local target="$3"
  local expected_units="$4"
  local rc

  log ""
  log "########## P0 segment ($kind) ##########"
  run_logged "$PY" "$UTIL/qda_segment.py" --source "$source" --out "$target"
  rc=$?
  log "  exit: $rc  -> $target"
  if [ "$rc" -ne 0 ] || [ ! -f "$target" ]; then
    log "  ABORT: P0 $kind failed; nothing downstream will run."
    return 1
  fi
  if ! "$PY" - "$target" "$expected_units" <<'PY' | tee -a "$SUM"
import json
import sys

path, expected = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
actual = data["meta"]["n_units"]
print(f"  n_units={actual}  source_sha256={data['meta']['source_sha256'][:16]}")
for unit in data["source_units"]:
    print(f"   {unit['unit_id']} [{unit.get('explicit_speaker')}] {unit['source_range']}")
if actual != expected:
    print(f"  ERROR: expected {expected} deterministic units, got {actual}")
    raise SystemExit(1)
PY
  then
    log "  ABORT: P0 $kind output does not match the deterministic fixture."
    return 1
  fi
  return 0
}

if ! segment_source SRT "$SRT" "$OUT/segments_srt.json" 4; then
  exit 20
fi
if ! segment_source TXT "$TXT" "$OUT/segments_txt.json" 5; then
  exit 21
fi

# ---------- one scenario = P1 + validation ----------
scenario() {
  local mode="$1"
  local tag="$2"
  shift 2
  local p1="$OUT/p1_${tag}.json"
  local vj="$OUT/validation_${tag}.json"
  local vm="$OUT/validation_${tag}.md"
  local quarantine="$OUT/quarantine/$tag"
  local prc=99
  local vrc=99
  local verdict="MISSING"
  local -a runner_args

  runner_args=(
    --units "$OUT/segments_srt.json"
    --schema "$SCHEMA"
    --model "$MODEL"
    --mode "$mode"
    --out "$p1"
  )
  if [ "$DRY" = "1" ]; then
    runner_args+=(--dry-run)
  else
    # The fixture is synthetic, so preserving invalid raw responses is safe and
    # materially improves diagnosis of real-model contract failures.
    runner_args+=(--quarantine-dir "$quarantine")
  fi
  runner_args+=("$@")

  log ""
  log "########## P1 ($mode) ##########"
  run_artifact_command "$PY" "$UTIL/qda_run_p1.py" "${runner_args[@]}"
  prc=$?
  log "  runner exit: $prc  -> $p1"

  if [ -f "$p1" ]; then
    if ! "$PY" - "$p1" <<'PY' | tee -a "$SUM"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle).get("_qda_run", {})
print("  statuses:", [item.get("status") for item in manifest.get("statuses", [])])
print(
    "  n_ok=%s/%s  provenance=%s  model_digest=%s"
    % (
        manifest.get("n_ok"),
        manifest.get("n_units"),
        manifest.get("provenance_level"),
        manifest.get("model_digest") or "None",
    )
)
PY
    then
      log "  ERROR: runner output is not readable as a DigQDA manifest."
      prc=98
    fi
  else
    log "  ERROR: runner produced no output; validation skipped."
  fi

  log ""
  log "########## VALIDATE ($mode) ##########"
  if [ -f "$p1" ]; then
    run_artifact_command "$PY" "$UTIL/qda_validate.py" \
      --source "$SRT" --json "$p1" --out "$vj" --report "$vm"
    vrc=$?
    if [ -f "$vj" ]; then
      verdict="$("$PY" - "$vj" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["_qda_validation"]["result"]["verdict"])
PY
)"
      "$PY" - "$vj" <<'PY' | tee -a "$SUM"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)["_qda_validation"]["result"]
print("  verdict:", result["verdict"])
print(
    "  quotes: exact=%s fuzzy=%s not_found=%s wrong_unit=%s missing=%s unbound=%s (total %s)"
    % (
        result["quotes_exact"],
        result["quotes_fuzzy"],
        result["quotes_not_found"],
        result["quotes_wrong_unit"],
        result["quotes_missing_evidence"],
        result["quotes_unbound"],
        result["quotes_total"],
    )
)
print(
    "  locators: invalid=%s / total=%s"
    % (result["locators_invalid"], result["locators_total"])
)
PY
    else
      log "  ERROR: validator produced no JSON result."
    fi
  else
    log "  skipped: no current runner output"
  fi
  log "  validator exit: $vrc  verdict=$verdict  -> $vm"

  if [ "$DRY" = "1" ]; then
    if [ "$prc" -ne 0 ] || [ "$vrc" -ne 2 ] || [ "$verdict" != "INVALID_INPUT" ]; then
      log "  SCENARIO_RESULT=FAIL (dry-run contract expectation not met)"
      RUN_FAILURES=$((RUN_FAILURES + 1))
      return 1
    fi
    log "  SCENARIO_RESULT=PASS (expected dry-run behavior)"
    return 0
  fi

  if [ "$prc" -ne 0 ] || [ "$vrc" -ne 0 ] || [ "$verdict" != "PASS" ]; then
    log "  SCENARIO_RESULT=REVIEW_REQUIRED"
    RUN_FAILURES=$((RUN_FAILURES + 1))
    return 1
  fi
  log "  SCENARIO_RESULT=PASS"
  return 0
}

scenario OPEN_DESCRIPTIVE open || true
scenario STRICT_CODEBOOK strict --codebook "$CB" || true

log ""
log "==================================================================="
if [ "$RUN_FAILURES" -eq 0 ]; then
  log " SMOKE_RESULT=PASS  failures=0"
  FINAL_RC=0
else
  log " SMOKE_RESULT=REVIEW_REQUIRED  failures=$RUN_FAILURES"
  FINAL_RC=1
fi
log ""
log " Synthetic artifacts safe to review in Codex:"
log "   • $SUM"
log "   • $OUT/p1_open.json      $OUT/validation_open.md"
log "   • $OUT/p1_strict.json    $OUT/validation_strict.md"
if [ "$DRY" != "1" ]; then
  log "   • $OUT/quarantine/ (only present for invalid raw responses)"
fi
log ""
log " Do not replace the bundled fixtures with real transcripts."
log " A real-data pilot requires the data-protection runbook first."
log "==================================================================="
exit "$FINAL_RC"

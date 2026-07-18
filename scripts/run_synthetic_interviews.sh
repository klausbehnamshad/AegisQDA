#!/usr/bin/env bash
# Fail-closed batch driver for the SYNTHETIC interview corpus.
#
# Runs each interview through the full state machine and asserts the EXPECTED
# terminal state per kind. It aggregates failures and exits non-zero if any run
# deviates. It is a plumbing smoke bound to the registered synthetic corpus, not
# a substitute for human review and not an anonymity claim.
#
# Expected outcomes:
#   clean / safe : scan -> auto-review -> transform -> analyze -> DOWNSTREAM_REVIEW_REQUIRED
#                  (--privacy-only deliberately stops at PRIVACY_RELEASED)
#   block        : scan -> auto-review STOPS (BLOCKED_BY_DESIGN); must NOT release
#
# By default a full run REQUIRES doctor READY (so analyze actually runs); it dies
# otherwise. Pass --privacy-only to deliberately smoke just scan→review→transform
# when no model/Ollama is available.
#
# Usage:
#   bash scripts/run_synthetic_interviews.sh                 # full run, doctor required
#   bash scripts/run_synthetic_interviews.sh --privacy-only  # privacy stages only
#   VENV=.venv MODEL=gemma3:4b RUN_ROOT=/private/tmp/aegisqda-runs bash scripts/run_synthetic_interviews.sh

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-$REPO/.venv}"
PY="$VENV/bin/python"
AEGIS="$VENV/bin/aegisqda"
RUN_ROOT="${RUN_ROOT:-/private/tmp/aegisqda-runs}"
REVIEWER="${REVIEWER:-SYNTHETIC-AUTOREVIEW}"
CORPUS="$REPO/tests/fixtures/interviews"
MODEL_ARG=()
[ "${MODEL:-}" != "" ] && MODEL_ARG=(--model "$MODEL")

PRIVACY_ONLY=0
for _a in "$@"; do
  case "$_a" in
    --privacy-only) PRIVACY_ONLY=1 ;;
    *) echo "FATAL: unknown argument: $_a" >&2; exit 1 ;;
  esac
done

FAILURES=0
PASSES=0
fail() { echo "   FAIL: $*"; FAILURES=$((FAILURES + 1)); }
pass() { echo "   ok:   $*"; PASSES=$((PASSES + 1)); }
hr()   { printf '%s\n' "------------------------------------------------------------"; }
die()  { echo "FATAL: $*" >&2; exit 1; }

# --- hard preconditions (fail-closed, never silent exit 0) ---
[ -x "$PY" ]    || die "python not found/executable at $PY (build the venv first)"
[ -x "$AEGIS" ] || die "aegisqda not found/executable at $AEGIS (pip install -e .)"
[ -d "$CORPUS" ] || die "corpus dir missing: $CORPUS"
"$PY" -c "import aegisqda" 2>/dev/null || die "aegisqda is not importable in $VENV"

echo "AegisQDA synthetic interview batch (fail-closed)"
echo "  repo=$REPO  venv=$VENV  run_root=$RUN_ROOT  model=${MODEL:-<config default>}"
hr

DOCTOR_JSON="$(mktemp -t aegis-doctor.XXXXXX)"
trap 'rm -f "$DOCTOR_JSON"' EXIT
"$AEGIS" doctor >"$DOCTOR_JSON" 2>/dev/null || true
GATE="$("$PY" -c "import json,sys
try: print(json.load(open('$DOCTOR_JSON')).get('gate','?'))
except Exception: print('?')" 2>/dev/null)"
READY=0; [ "$GATE" = "READY" ] && READY=1
if [ "$READY" -ne 1 ] && [ "$PRIVACY_ONLY" -ne 1 ]; then
  die "doctor gate is $GATE (not READY); a full scan→…→analyze run is not possible. Fix doctor (Ollama + gemma3:4b + pinned DigQDA), or re-run with --privacy-only to smoke only the privacy stages."
fi
if [ "$PRIVACY_ONLY" -eq 1 ]; then
  echo "doctor gate: $GATE — PRIVACY-ONLY mode: analyze is skipped by request."
else
  echo "doctor gate: $GATE — full run (analyze will execute)."
fi
hr

# lang | file | kind | case-id
ROWS=(
  "de|expert_clean.srt|clean|SYNTH-DE-CLEAN"
  "de|participant_blockdemo.txt|block|SYNTH-DE-BLOCK"
  "de|safe_control.txt|safe|SYNTH-DE-SAFE"
  "fr|expert_clean.srt|clean|SYNTH-FR-CLEAN"
  "fr|participant_blockdemo.txt|block|SYNTH-FR-BLOCK"
  "fr|safe_control.txt|safe|SYNTH-FR-SAFE"
  "en|expert_clean.srt|clean|SYNTH-EN-CLEAN"
  "en|participant_blockdemo.txt|block|SYNTH-EN-BLOCK"
  "en|safe_control.txt|safe|SYNTH-EN-SAFE"
)

run_one() {
  local lang="$1" file="$2" kind="$3" case_id="$4"
  local src="$CORPUS/$lang/$file"
  echo ">> $lang/$file  [$kind]"

  local scan_out scan_rc run_dir
  scan_out="$("$AEGIS" scan "$src" --language "$lang" --case-id "$case_id" \
             --run-root "$RUN_ROOT" --synthetic 2>&1)"; scan_rc=$?
  run_dir="$(printf '%s\n' "$scan_out" | sed -n 's/^run_dir=//p')"
  # scan intentionally returns 3 (REVIEW_REQUIRED); anything else is a failure
  if [ "$scan_rc" -ne 3 ] || [ -z "$run_dir" ]; then
    fail "$lang/$file scan did not reach REVIEW_REQUIRED (rc=$scan_rc)"; return
  fi

  local rev_out rev_rc
  rev_out="$("$PY" "$REPO/scripts/auto_review_synthetic.py" "$run_dir" --reviewer "$REVIEWER" 2>&1)"; rev_rc=$?

  if [ "$kind" = "block" ]; then
    # expected: auto-review STOPS with BLOCKED_BY_DESIGN (rc=3), no release
    if [ "$rev_rc" -eq 3 ] && printf '%s' "$rev_out" | grep -q "BLOCKED_BY_DESIGN"; then
      pass "$lang/$file blocked at review as expected (indirect identifiers)"
    else
      fail "$lang/$file block-demo did NOT block at review (rc=$rev_rc)"
    fi
    return
  fi

  # clean / safe: must accept review, transform, and (if READY) analyze
  if [ "$rev_rc" -ne 0 ]; then
    fail "$lang/$file auto-review failed (rc=$rev_rc): $(printf '%s' "$rev_out" | head -1)"; return
  fi
  local tf_out tf_rc
  tf_out="$("$AEGIS" transform "$run_dir" 2>&1)"; tf_rc=$?
  if [ "$tf_rc" -ne 0 ] || ! printf '%s\n' "$tf_out" | grep -q '^PRIVACY_RELEASED$'; then
    fail "$lang/$file transform blocked (rc=$tf_rc): $(printf '%s' "$tf_out" | head -1)"; return
  fi
  if [ "$PRIVACY_ONLY" -eq 1 ] || [ "$READY" -ne 1 ]; then
    pass "$lang/$file PRIVACY_RELEASED (analyze skipped: privacy-only)"; return
  fi
  local an_out an_rc
  an_out="$("$AEGIS" analyze "$run_dir" "${MODEL_ARG[@]}" 2>&1)"; an_rc=$?
  if [ "$an_rc" -eq 0 ] && printf '%s\n' "$an_out" | grep -q '^DOWNSTREAM_REVIEW_REQUIRED$'; then
    pass "$lang/$file DOWNSTREAM_REVIEW_REQUIRED"
  else
    fail "$lang/$file analyze blocked (rc=$an_rc): $(printf '%s' "$an_out" | head -1)"
  fi
}

for row in "${ROWS[@]}"; do
  IFS='|' read -r lang file kind case_id <<<"$row"
  run_one "$lang" "$file" "$kind" "$case_id"
done

hr
echo "SUMMARY: $PASSES ok, $FAILURES failed. Run artifacts under $RUN_ROOT (outside Git)."
[ "$FAILURES" -eq 0 ] || echo "Batch FAILED — see per-row FAIL lines above."
exit "$FAILURES"

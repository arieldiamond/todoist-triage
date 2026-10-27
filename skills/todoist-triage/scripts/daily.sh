#!/bin/bash
# Daily dry-run: fetch -> (Claude judges leftovers) -> plan -> post digest to the Focus task. Never applies changes.
# Python/PATH come from the scheduler (see `triage.py install-schedule`); falls back to whatever is on PATH.
set -u
PY="${TRIAGE_PY:-python3}"
SK="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${TODOIST_TRIAGE_HOME:-$HOME/.todoist-triage}"
cd "$SK" || exit 1
OUT=$($PY scripts/triage.py fetch) || { echo "$OUT"; exit 1; }
echo "$OUT"
RUN=$(echo "$OUT" | sed -n 's/^run: //p')
if echo "$OUT" | grep -q '^tasks: 0 '; then
  $PY scripts/triage.py digest --post
  exit 0
fi
if [ -s "$RUN/needs_llm.json" ] && [ "$($PY -c "import json;print(len(json.load(open('$RUN/needs_llm.json'))))")" -gt 0 ]; then
  if command -v claude >/dev/null 2>&1; then
    PROMPT="You are the judgment step of the todoist-triage skill (dry run). Read $SK/references/schema.md and $RUN/needs_llm.json. Output ONLY a JSON object mapping each task id to its overrides, in the format described in $SK/SKILL.md step 2. No prose, no code fences."
    claude -p "$PROMPT" --model "${TRIAGE_MODEL:-sonnet}" --allowedTools Read --no-session-persistence < /dev/null > "$RUN/llm.raw" 2> "$RUN/llm.err"
    $PY - "$RUN" <<'PYEOF' || echo "llm output invalid; continuing with rules only"
import json, re, sys
raw = open(sys.argv[1] + '/llm.raw').read()
m = re.search(r'\{.*\}', raw, re.S)
json.dump(json.loads(m.group(0)), open(sys.argv[1] + '/llm.json', 'w'), indent=1)
PYEOF
  else
    echo "claude CLI not found; unresolved tasks stay unsectioned for you to sort"
  fi
fi
$PY scripts/triage.py plan "$RUN" > "$RUN/plan.txt" || exit 1
# Opt-in auto mode: TRIAGE_AUTO=1 applies confident items, gated on the held-out eval score. Default stays dry-run.
if [ "${TRIAGE_AUTO:-0}" = 1 ] && $PY scripts/triage.py eval --split test --min 0.9 > "$RUN/eval.txt" 2>&1; then
  $PY scripts/triage.py apply "$RUN" --yes > "$RUN/apply.txt" 2>&1 || echo "apply failed; see $RUN/apply.txt"
fi
$PY scripts/triage.py digest --post --run "$RUN"

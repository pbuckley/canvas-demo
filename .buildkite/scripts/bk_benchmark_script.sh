#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Buildkite Pipeline Benchmarker
# Usage:
#   export BK_API_TOKEN=<token>
#   export BK_ORG_SLUG=<org-slug>
#   bash bk_benchmark_script.sh <pipeline_slug> <number_of_runs>
#
# Refs:
#   Create build : POST /v2/organizations/{org}/pipelines/{pipeline}/builds
#   Get build    : GET  /v2/organizations/{org}/pipelines/{pipeline}/builds/{number}
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# ── Colour helpers (only if terminal supports it) ─────────────
if [[ -t 2 ]] && tput colors &>/dev/null && [[ "$(tput colors)" -ge 8 ]]; then
  RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
  CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
  RED=''; YELLOW=''; GREEN=''; CYAN=''; BOLD=''; RESET=''
fi

err()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*" >&2; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*" >&2; }

# ── Print a copy-pasteable curl command to stderr ─────────────
show_curl() {
  local method="$1" url="$2" payload="${3:-}"
  echo -e "${CYAN}[CMD]${RESET}  curl -sS -w '\\n%{http_code}' \\" >&2
  echo    "         -H 'Authorization: Bearer ***' \\" >&2
  if [[ -n "$payload" ]]; then
    echo  "         -H 'Content-Type: application/json' \\" >&2
    echo  "         -X ${method} '${url}' \\" >&2
    echo  "         -d '${payload}'" >&2
  else
    echo  "         -X ${method} '${url}'" >&2
  fi
}

# ── Arg / env validation ──────────────────────────────────────
[[ $# -lt 2 || $# -gt 3 ]] && { err "Usage: $0 <pipeline_slug> <number_of_runs> [--dry-run]"; exit 1; }

PIPELINE="$1"
NUM_RUNS="$2"
DRY_RUN=false
[[ "${3:-}" == "--dry-run" ]] && DRY_RUN=true
BASE_URL="https://api.buildkite.com/v2"

[[ -z "${BK_API_TOKEN:-}" ]] && { err "BK_API_TOKEN is not set."; exit 1; }
[[ -z "${BK_ORG_SLUG:-}"  ]] && { err "BK_ORG_SLUG is not set.";  exit 1; }
[[ ! "$NUM_RUNS" =~ ^[1-9][0-9]*$ ]] && { err "number_of_runs must be a positive integer."; exit 1; }

# ── Dependency check ──────────────────────────────────────────
for cmd in curl jq bc; do
  command -v "$cmd" &>/dev/null || { err "Required tool not found: $cmd"; exit 1; }
done

AUTH_HEADER="Authorization: Bearer ${BK_API_TOKEN}"
PIPELINE_URL="${BASE_URL}/organizations/${BK_ORG_SLUG}/pipelines/${PIPELINE}"

# ── Token smoke test: validate token and check scopes ─────────
# GET /v2/access-token returns the token's owner and granted scopes
info "Validating API token..."
TOKEN_RESP=$(curl -sS -w "\n%{http_code}" -H "$AUTH_HEADER" \
  "${BASE_URL}/access-token" 2>&1)
TOKEN_HTTP=$(echo "$TOKEN_RESP" | tail -n1)
TOKEN_BODY=$(echo "$TOKEN_RESP" | sed '$d')

if [[ "$TOKEN_HTTP" -eq 401 ]]; then
  err "API token is invalid or revoked (HTTP 401)."
  show_curl "GET" "${BASE_URL}/access-token"
  exit 1
elif [[ "$TOKEN_HTTP" -lt 200 || "$TOKEN_HTTP" -ge 300 ]]; then
  err "Unexpected response validating token (HTTP ${TOKEN_HTTP})."
  show_curl "GET" "${BASE_URL}/access-token"
  echo "$TOKEN_BODY" | jq '.' 2>/dev/null || echo "$TOKEN_BODY"
  exit 1
fi

TOKEN_USER=$(echo "$TOKEN_BODY"   | jq -r '.user.name // "unknown"')
TOKEN_EMAIL=$(echo "$TOKEN_BODY"  | jq -r '.user.email // "unknown"')
TOKEN_SCOPES=$(echo "$TOKEN_BODY" | jq -r '.scopes | join(", ")')
info "Token OK — owner: ${TOKEN_USER} <${TOKEN_EMAIL}>"
info "Scopes: ${TOKEN_SCOPES}"

# Warn if required scopes appear to be missing
REQUIRED_SCOPES=("read_pipelines" "write_builds")
for scope in "${REQUIRED_SCOPES[@]}"; do
  if ! echo "$TOKEN_SCOPES" | grep -qw "$scope"; then
    warn "Scope '${scope}' not found in token — this may cause failures."
  fi
done

# ── Verify pipeline exists and get default branch ─────────────
info "Looking up pipeline '${PIPELINE}' in org '${BK_ORG_SLUG}'..."
show_curl "GET" "${PIPELINE_URL}"
PIPELINE_RESP=$(curl -sS -w "\n%{http_code}" -H "$AUTH_HEADER" "${PIPELINE_URL}" 2>&1)
PIPELINE_HTTP=$(echo "$PIPELINE_RESP" | tail -n1)
PIPELINE_JSON=$(echo "$PIPELINE_RESP" | sed '$d')

if [[ "$PIPELINE_HTTP" -lt 200 || "$PIPELINE_HTTP" -ge 300 ]]; then
  err "Failed to fetch pipeline '${PIPELINE}' in org '${BK_ORG_SLUG}' — HTTP ${PIPELINE_HTTP}"
  PIPELINE_MSG=$(echo "$PIPELINE_JSON" | jq -r '.message // empty' 2>/dev/null)
  [[ -n "$PIPELINE_MSG" ]] && err "Buildkite says: ${PIPELINE_MSG}"
  case "$PIPELINE_HTTP" in
    401) err "Token is not authorised for org '${BK_ORG_SLUG}'. Check the token's Organisation Access in your Personal Settings." ;;
    403) err "Token lacks permission to read pipelines in '${BK_ORG_SLUG}'. Ensure 'read_pipelines' scope is granted." ;;
    404) err "Pipeline or org not found. Verify BK_ORG_SLUG='${BK_ORG_SLUG}' and pipeline slug '${PIPELINE}' are correct." ;;
  esac
  exit 1
fi
DEFAULT_BRANCH=$(echo "$PIPELINE_JSON" | jq -r '.default_branch // "main"')
PIPELINE_NAME=$(echo "$PIPELINE_JSON"  | jq -r '.name')
PROVIDER_ID=$(echo "$PIPELINE_JSON"    | jq -r '.provider.id // "unknown"')
BUILD_BRANCHES=$(echo "$PIPELINE_JSON" | jq -r 'if .provider.settings.build_branches == false then "false" else "true" end')
info "Found: ${PIPELINE_NAME} (default branch: ${DEFAULT_BRANCH}, provider: ${PROVIDER_ID})"

# ── Resolve the commit SHA to use ────────────────────────────
# "Build branches: false" blocks the API when a branch name is passed, because
# Buildkite's provider settings layer intercepts it before checkout.
# Workaround: look up the most recent build's actual commit SHA on the default
# branch and use that instead. A real SHA bypasses the branch-name guard while
# still checking out the right code. Falls back to "HEAD" if no prior build exists.
COMMIT_SHA="HEAD"
REBUILD_NUMBER=""
if [[ "$BUILD_BRANCHES" == "false" ]]; then
  echo -e "${YELLOW}[WARN]${RESET}  Pipeline has 'Build branches' disabled."
  info "Resolving latest build on '${DEFAULT_BRANCH}' to use rebuild endpoint..."
  RECENT_BUILD_JSON=$(curl -sf -H "$AUTH_HEADER" \
    "${PIPELINE_URL}/builds?branch=${DEFAULT_BRANCH}&per_page=1") || true
  REBUILD_NUMBER=$(echo "$RECENT_BUILD_JSON" | jq -r '.[0].number // empty')
  COMMIT_SHA=$(echo "$RECENT_BUILD_JSON"     | jq -r '.[0].commit // "HEAD"')
  if [[ -n "$REBUILD_NUMBER" && "$REBUILD_NUMBER" != "null" ]]; then
    info "Will use rebuild of build #${REBUILD_NUMBER} (commit: ${COMMIT_SHA})"
  else
    echo -e "${YELLOW}[WARN]${RESET}  No prior build found on '${DEFAULT_BRANCH}'."
    echo -e "         Cannot benchmark this pipeline without at least one prior build."
    echo -e "         Run a build manually first, or enable 'Build branches' in pipeline settings."
    exit 1
  fi
fi

# ── Dry-run: show what would be triggered and exit ───────────
if [[ "$DRY_RUN" == "true" ]]; then
  echo ""
  warn "DRY RUN — no builds will be triggered"
  echo -e "${BOLD}  Pipeline : ${PIPELINE_NAME}${RESET}"
  echo -e "${BOLD}  Org      : ${BK_ORG_SLUG}${RESET}"
  echo -e "${BOLD}  Runs     : ${NUM_RUNS}${RESET}"
  echo ""
  for ((i=1; i<=NUM_RUNS; i++)); do
    if [[ -n "$REBUILD_NUMBER" ]]; then
      echo -e "  Run ${i}/${NUM_RUNS} — would rebuild #${REBUILD_NUMBER}:"
      show_curl "PUT" "${PIPELINE_URL}/builds/${REBUILD_NUMBER}/rebuild"
    else
      PAYLOAD="{\"branch\": \"${DEFAULT_BRANCH}\", \"commit\": \"${COMMIT_SHA}\", \"message\": \"bk-benchmark run ${i}/${NUM_RUNS}\"}"
      echo -e "  Run ${i}/${NUM_RUNS} — would create build:"
      show_curl "POST" "${PIPELINE_URL}/builds" "$PAYLOAD"
    fi
    echo ""
  done
  info "Dry run complete. Re-run without --dry-run to execute."
  exit 0
fi

# ── Fire all builds in parallel ───────────────────────────────
# Think of this like sending N runners to the starting line simultaneously,
# then watching the finish line for all of them.

BUILD_NUMBERS=()   # build numbers returned by the API
LAUNCH_TIMES=()    # epoch seconds we fired each request (local wall clock)

info "Triggering ${NUM_RUNS} build(s) in parallel..."
for ((i=1; i<=NUM_RUNS; i++)); do
  LAUNCH_TIMES+=("$(date +%s)")

  if [[ -n "$REBUILD_NUMBER" ]]; then
    BUILD_ENDPOINT="${PIPELINE_URL}/builds/${REBUILD_NUMBER}/rebuild"
    show_curl "PUT" "${BUILD_ENDPOINT}"
    HTTP_RESP=$(curl -sS -w "\n%{http_code}" \
      -H "$AUTH_HEADER" -H "Content-Type: application/json" \
      -X PUT "${BUILD_ENDPOINT}" 2>&1)
  else
    BUILD_ENDPOINT="${PIPELINE_URL}/builds"
    BUILD_PAYLOAD="{\"branch\": \"${DEFAULT_BRANCH}\", \"commit\": \"${COMMIT_SHA}\", \"message\": \"bk-benchmark run ${i}/${NUM_RUNS}\"}"
    show_curl "POST" "${BUILD_ENDPOINT}" "${BUILD_PAYLOAD}"
    HTTP_RESP=$(curl -sS -w "\n%{http_code}" \
      -H "$AUTH_HEADER" -H "Content-Type: application/json" \
      -X POST "${BUILD_ENDPOINT}" \
      -d "${BUILD_PAYLOAD}" 2>&1)
  fi

  HTTP_CODE=$(echo "$HTTP_RESP" | tail -n1)
  RESP_BODY=$(echo "$HTTP_RESP" | sed '$d')

  if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
    err "Failed to trigger build ${i} — HTTP ${HTTP_CODE}"
    err "Response body:"
    echo "$RESP_BODY" | jq '.' 2>/dev/null || echo "$RESP_BODY"
    exit 1
  fi

  NUM=$(echo "$RESP_BODY" | jq -r '.number // empty')
  if [[ -z "$NUM" ]]; then
    err "Build triggered (HTTP ${HTTP_CODE}) but could not parse build number from response."
    err "Response body:"
    echo "$RESP_BODY" | jq '.' 2>/dev/null || echo "$RESP_BODY"
    exit 1
  fi

  BUILD_NUMBERS+=("$NUM")
  echo -e "  ${CYAN}↑${RESET} Triggered build #${NUM} (run ${i}/${NUM_RUNS})"
done

# ── Poll until all builds reach a terminal state ──────────────
# Terminal states per Buildkite docs: passed, failed, blocked,
# canceled, skipped, not_run
TERMINAL_STATES="passed|failed|blocked|canceled|skipped|not_run"
POLL_INTERVAL=30      # seconds between sweeps
HEARTBEAT_EVERY=4    # print "still running" every N polls (~2 min at 30s)

declare -A BUILD_STATE       # build_number → final state
declare -A BUILD_JSON_CACHE  # build_number → final JSON blob

pending=("${BUILD_NUMBERS[@]}")
poll_count=0

info "Polling for completion (${#pending[@]} builds pending, checking every ${POLL_INTERVAL}s)..."
while [[ ${#pending[@]} -gt 0 ]]; do
  sleep "$POLL_INTERVAL"
  (( poll_count++ )) || true
  still_pending=()

  for num in "${pending[@]}"; do
    bjson=$(curl -sf -H "$AUTH_HEADER" \
      "${PIPELINE_URL}/builds/${num}") || { still_pending+=("$num"); continue; }
    state=$(echo "$bjson" | jq -r '.state')

    if [[ "$state" =~ ^($TERMINAL_STATES)$ ]]; then
      BUILD_STATE["$num"]="$state"
      BUILD_JSON_CACHE["$num"]="$bjson"
      echo -e "  ${GREEN}✓${RESET} Build #${num} → ${state}"
    else
      still_pending+=("$num")
    fi
  done

  pending=("${still_pending[@]}")
  if [[ ${#pending[@]} -gt 0 && $(( poll_count % HEARTBEAT_EVERY )) -eq 0 ]]; then
    elapsed=$(( poll_count * POLL_INTERVAL ))
    info "Still running after ${elapsed}s: builds ${pending[*]}"
  fi
done

# ── Helper: ISO 8601 timestamp → epoch seconds ────────────────
iso_to_epoch() {
  # Works on both GNU date (Linux) and BSD date (macOS)
  local ts="$1"
  if date --version &>/dev/null 2>&1; then
    # GNU
    date -d "$ts" +%s 2>/dev/null || echo ""
  else
    # BSD / macOS
    date -jf "%Y-%m-%dT%H:%M:%S" "${ts%%.*}" +%s 2>/dev/null || echo ""
  fi
}

# ── Print results ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}┌─────────┬──────────┬──────────┬──────────┐${RESET}"
echo -e "${BOLD}│  BUILD  │  WALL(s) │ QUEUE(s) │  RUN(s)  │${RESET}"
echo -e "${BOLD}├─────────┼──────────┼──────────┼──────────┤${RESET}"

# Accumulators for summary
wall_times=(); queue_times=(); run_times=()
failed_count=0

for ((i=0; i<NUM_RUNS; i++)); do
  num="${BUILD_NUMBERS[$i]}"
  state="${BUILD_STATE[$num]}"
  bjson="${BUILD_JSON_CACHE[$num]}"

  created_at=$(echo  "$bjson" | jq -r '.created_at  // empty')
  started_at=$(echo  "$bjson" | jq -r '.started_at  // empty')
  finished_at=$(echo "$bjson" | jq -r '.finished_at // empty')

  wall_s="N/A"; queue_s="N/A"; run_s="N/A"
  if [[ -n "$created_at" && -n "$finished_at" ]]; then
    e_created=$(iso_to_epoch "$created_at")
    e_finished=$(iso_to_epoch "$finished_at")
    if [[ -n "$e_created" && -n "$e_finished" ]]; then
      wall_s=$(( e_finished - e_created ))
      wall_times+=("$wall_s")
    fi
  fi
  if [[ -n "$created_at" && -n "$started_at" ]]; then
    e_created=$(iso_to_epoch "$created_at")
    e_started=$(iso_to_epoch "$started_at")
    if [[ -n "$e_created" && -n "$e_started" ]]; then
      queue_s=$(( e_started - e_created ))
      queue_times+=("$queue_s")
    fi
  fi
  if [[ -n "$started_at" && -n "$finished_at" ]]; then
    e_started=$(iso_to_epoch "$started_at")
    e_finished=$(iso_to_epoch "$finished_at")
    if [[ -n "$e_started" && -n "$e_finished" ]]; then
      run_s=$(( e_finished - e_started ))
      run_times+=("$run_s")
    fi
  fi

  case "$state" in
    passed) state_colour="${GREEN}" ;;
    failed) state_colour="${RED}";    ((failed_count++)) ;;
    *)      state_colour="${YELLOW}"; ((failed_count++)) ;;
  esac
  printf "│ ${state_colour}●${RESET} %-5s │ %8s │ %8s │ %8s │\n" \
    "#${num}" "${wall_s}" "${queue_s}" "${run_s}"
done

echo -e "${BOLD}└─────────┴──────────┴──────────┴──────────┘${RESET}"

# ── Summary stats ─────────────────────────────────────────────
avg() {
  local -n arr=$1
  [[ ${#arr[@]} -eq 0 ]] && echo "N/A" && return
  local sum=0
  for v in "${arr[@]}"; do sum=$((sum + v)); done
  echo "scale=1; $sum / ${#arr[@]}" | bc
}

min_val() {
  local -n arr=$1
  [[ ${#arr[@]} -eq 0 ]] && echo "N/A" && return
  local m="${arr[0]}"
  for v in "${arr[@]}"; do (( v < m )) && m=$v; done
  echo "$m"
}

max_val() {
  local -n arr=$1
  [[ ${#arr[@]} -eq 0 ]] && echo "N/A" && return
  local m="${arr[0]}"
  for v in "${arr[@]}"; do (( v > m )) && m=$v; done
  echo "$m"
}

echo ""
echo -e "${BOLD}  ${PIPELINE_NAME} — ${NUM_RUNS} run(s)${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
printf "  %-32s %s / %s passed\n" "Outcome:" "$((NUM_RUNS - failed_count))" "${NUM_RUNS}"
echo ""
printf "  %-32s %8s  %8s  %8s\n" ""                             "avg(s)"  "min(s)"  "max(s)"
printf "  %-32s %8s  %8s  %8s\n" "Wall  (created → finished):"  "$(avg wall_times)"  "$(min_val wall_times)"  "$(max_val wall_times)"
printf "  %-32s %8s  %8s  %8s\n" "Queue (created → started):"   "$(avg queue_times)" "$(min_val queue_times)" "$(max_val queue_times)"
printf "  %-32s %8s  %8s  %8s\n" "Run   (started → finished):"  "$(avg run_times)"   "$(min_val run_times)"   "$(max_val run_times)"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

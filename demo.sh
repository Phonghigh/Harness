#!/usr/bin/env bash
# Harness demo — full stub workflow, no API key required
# Usage: bash demo.sh            (interactive, pauses between steps)
#        bash demo.sh --no-pause (runs straight through)

set -euo pipefail

NO_PAUSE=false
[[ "${1:-}" == "--no-pause" ]] && NO_PAUSE=true

DEMO_DIR=$(mktemp -d)
trap 'rm -rf "$DEMO_DIR"' EXIT

BOLD="\033[1m"; CYAN="\033[36m"; GREEN="\033[32m"; DIM="\033[2m"; RESET="\033[0m"

step()  { echo -e "\n${CYAN}${BOLD}▶ $*${RESET}"; }
run()   { echo -e "  ${DIM}\$ $*${RESET}"; eval "$@"; }
pause() { $NO_PAUSE && return; echo -e "\n${DIM}Press Enter to continue...${RESET}"; read -r; }

# ── header ───────────────────────────────────────────────────────────────────

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════╗"
echo "║         Harness — Architect-Driven Coding         ║"
echo "║          Stub Workflow Demo (no API key)          ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo "Temp project: $DEMO_DIR"
cd "$DEMO_DIR"

# ── 1. init ──────────────────────────────────────────────────────────────────

step "1/12  Init project"
run harness init --provider anthropic --model claude-sonnet-4-6
pause

# ── 2. start ─────────────────────────────────────────────────────────────────

step "2/12  Start a task"
run harness start '"Add JWT authentication to the REST API"'
pause

# ── 3. interrogate ───────────────────────────────────────────────────────────

step "3/12  Interrogate — generate architecture decisions (stub)"
run harness interrogate
pause

# ── 4. decisions ─────────────────────────────────────────────────────────────

step "4/12  Review pending decisions"
run harness decisions
pause

# ── 5. answer ────────────────────────────────────────────────────────────────

step "5/12  Answer each decision"
# Collect pending decision IDs
DIDS=$(harness decisions 2>/dev/null \
  | grep -oP '(?<=│ )D\d+(?= │)' \
  | head -10)

ANSWERS=(
  "id, user_id, token_hash, expires_at, created_at, revoked"
  "Use DTO pattern — never expose internal entity fields in the API"
  "Tokens expire after 24 h; revoked tokens stored in Redis blacklist"
)
i=0
for DID in $DIDS; do
  ANS="${ANSWERS[$i]:-Use recommended approach}"
  run harness answer "$DID" "\"$ANS\""
  i=$(( i + 1 ))
done
pause

# ── 6. approve ───────────────────────────────────────────────────────────────

step "6/12  Approve all decisions at once"
run harness approve --all
pause

# ── 7. contract ──────────────────────────────────────────────────────────────

step "7/12  Build implementation contract (stub JSON)"
run harness contract
pause

# ── 8. contract-approve ──────────────────────────────────────────────────────

step "8/12  Architect reviews and approves the contract"
echo -e "  ${DIM}(In a real flow: open .harness/patches/ and read the spec before approving)${RESET}"
run harness contract-approve
pause

# ── 9. implement ─────────────────────────────────────────────────────────────

step "9/12  Generate the patch (stub diff)"
run harness implement C001
echo
echo -e "  ${DIM}Patch written to: .harness/patches/C001.diff${RESET}"
echo -e "  ${DIM}--- preview ---${RESET}"
cat .harness/patches/C001.diff | sed 's/^/  /'
pause

# ── 10. apply ────────────────────────────────────────────────────────────────

step "10/12  Approve patch → advance to compliance checking"
echo -e "  ${DIM}(In a real flow: git diff to inspect before applying)${RESET}"
run harness apply
pause

# ── 11. check + validate ─────────────────────────────────────────────────────

step "11/12  Compliance check, then validate"
run harness check C001
run harness validate
pause

# ── 12. remember + observe ───────────────────────────────────────────────────

step "12/12  Extract memories, then inspect the audit trail"
run harness remember
echo
run harness trace
echo
run harness memory list
pause

# ── done ─────────────────────────────────────────────────────────────────────

echo -e "\n${GREEN}${BOLD}✓ Done — full workflow complete in stub mode${RESET}"
echo
echo "Next steps:"
echo "  export ANTHROPIC_API_KEY=sk-ant-..."
echo "  harness run \"your real requirement here\""

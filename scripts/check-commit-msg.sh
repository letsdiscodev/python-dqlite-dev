#!/usr/bin/env bash
#
# Reject commit messages that carry internal workflow vocabulary
# ("Round N", "Cycle N", "Phase N", "Bundle N", ISSUE-N tokens,
# done/<file>.md references, "this round" prose). Shared by all four
# dqlite Python packages; see each repo's DEVELOPMENT.md.
#
set -euo pipefail

# Capital-leading-or-lowercase workflow tokens with a numeric counter.
WORKFLOW_RE='\b(round|cycle|phase|bundle)\s+[0-9]+\b'

# ISSUE-N tokens (e.g. ISSUE-T4, ISSUE-42) and done/ filename refs.
ISSUE_RE='\bISSUE-[A-Z0-9]+\b'
DONE_RE='\bdone/[A-Za-z0-9._-]+\.md\b'

# "ultrathink" / "this round" / "next round" prose markers.
PROSE_RE='\b(ultrathink|this round|next round|prior round|earlier round)\b'

scan_text() {
    # $1 — label (file path or commit SHA) for the report.
    # stdin — message body to scan.
    local label="$1"
    local body
    body="$(cat)"
    local rc=0
    # Strip comment lines (git commit message convention: '#' at column 0).
    local stripped
    stripped="$(printf '%s\n' "$body" | grep -v '^#' || true)"

    if printf '%s\n' "$stripped" | grep -inE "$WORKFLOW_RE" >/dev/null; then
        printf 'check-commit-msg: %s: workflow token (Round/Cycle/Phase/Bundle N) detected\n' "$label" >&2
        printf '%s\n' "$stripped" | grep -inE "$WORKFLOW_RE" >&2 || true
        rc=1
    fi
    if printf '%s\n' "$stripped" | grep -inE "$ISSUE_RE" >/dev/null; then
        printf 'check-commit-msg: %s: ISSUE-N token detected\n' "$label" >&2
        printf '%s\n' "$stripped" | grep -inE "$ISSUE_RE" >&2 || true
        rc=1
    fi
    if printf '%s\n' "$stripped" | grep -inE "$DONE_RE" >/dev/null; then
        printf 'check-commit-msg: %s: done/ filename reference detected\n' "$label" >&2
        printf '%s\n' "$stripped" | grep -inE "$DONE_RE" >&2 || true
        rc=1
    fi
    if printf '%s\n' "$stripped" | grep -inE "$PROSE_RE" >/dev/null; then
        printf 'check-commit-msg: %s: workflow prose marker detected\n' "$label" >&2
        printf '%s\n' "$stripped" | grep -inE "$PROSE_RE" >&2 || true
        rc=1
    fi
    return $rc
}

usage() {
    cat >&2 <<'EOF'
Usage:
  check-commit-msg.sh <file>           lint a single commit-message file
  check-commit-msg.sh -                lint message read from stdin
  check-commit-msg.sh --range <rev>    lint every commit in the rev range
EOF
    exit 2
}

if [ $# -lt 1 ]; then
    usage
fi

case "$1" in
    --range)
        if [ $# -ne 2 ]; then
            usage
        fi
        rc=0
        for sha in $(git rev-list "$2"); do
            if ! git log -1 --format=%B "$sha" | scan_text "$sha"; then
                rc=1
            fi
        done
        exit $rc
        ;;
    -)
        scan_text "<stdin>"
        ;;
    -h|--help)
        usage
        ;;
    *)
        if [ ! -f "$1" ]; then
            printf 'check-commit-msg: %s: not a file\n' "$1" >&2
            exit 2
        fi
        scan_text "$1" < "$1"
        ;;
esac

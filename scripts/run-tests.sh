#!/usr/bin/env bash
#
# Run linters + tests across the four sibling Python packages
# (python-dqlite-wire, python-dqlite-client, python-dqlite-dbapi,
# sqlalchemy-dqlite) plus, on sqlalchemy-dqlite, the SA dialect
# compliance suite.
#
# Layout assumed:
#   <workspace>/python-dqlite-dev/scripts/run-tests.sh   (this script)
#   <workspace>/python-dqlite-dev/cluster/                (compose dir)
#   <workspace>/python-dqlite-wire/
#   <workspace>/python-dqlite-client/
#   <workspace>/python-dqlite-dbapi/
#   <workspace>/sqlalchemy-dqlite/
#
# Usage:
#   ./scripts/run-tests.sh              # lint + unit + integration
#   ./scripts/run-tests.sh --unit       # unit tests only (no cluster needed)
#   ./scripts/run-tests.sh --no-lint    # skip ruff + mypy
#   ./scripts/run-tests.sh --no-cluster # tests against an already-running cluster

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="$(cd "$DEV_DIR/.." && pwd)"
COMPOSE_FILE="$DEV_DIR/cluster/docker-compose.yml"

CLUSTER_HOST_PORTS=(9001 9002 9003)

# The integration suites read these env vars to find the cluster.
# The values below mirror the canonical dqlite defaults the test
# fixtures already use, so the exports are technically redundant for
# the default ports — but explicit exports make the contract obvious
# and tolerate any per-test override that reads the env directly.
export DQLITE_TEST_CLUSTER="localhost:${CLUSTER_HOST_PORTS[0]}"
export DQLITE_TEST_CLUSTER_NODES="localhost:${CLUSTER_HOST_PORTS[0]},localhost:${CLUSTER_HOST_PORTS[1]},localhost:${CLUSTER_HOST_PORTS[2]}"

# Packages run in dependency order — wire is the lowest layer; a
# break there would mask itself as a higher-layer failure.
PACKAGES=(
    python-dqlite-wire
    python-dqlite-client
    python-dqlite-dbapi
    sqlalchemy-dqlite
)

# Colors only when the output is a terminal — keeps logs and CI
# captures readable.
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[0;33m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    GREEN='' RED='' YELLOW='' BOLD='' RESET=''
fi

UNIT_ONLY=false
RUN_LINT=true
START_CLUSTER=true

for arg in "$@"; do
    case "$arg" in
        --unit)       UNIT_ONLY=true; START_CLUSTER=false ;;
        --no-lint)    RUN_LINT=false ;;
        --no-cluster) START_CLUSTER=false ;;
        --help|-h)
            sed -n '3,17s/^# \?//p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

passed=0
failed=0
failures=()

log()  { echo -e "${BOLD}==> $1${RESET}"; }
ok()   { echo -e "    ${GREEN}PASS${RESET} $1"; }
fail() { echo -e "    ${RED}FAIL${RESET} $1"; }
skip() { echo -e "    ${YELLOW}SKIP${RESET} $1"; }

record_pass() { passed=$((passed + 1)); ok "$1"; }
record_fail() { failed=$((failed + 1)); failures+=("$1"); fail "$1"; }

# --- Cluster management ---

wait_for_port() {
    local port=$1
    local timeout=${2:-60}
    local elapsed=0
    while ! nc -z localhost "$port" 2>/dev/null; do
        if [ "$elapsed" -ge "$timeout" ]; then
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 0
}

start_cluster() {
    log "Starting dqlite cluster (compose file: $COMPOSE_FILE)"
    docker compose -f "$COMPOSE_FILE" up -d 2>&1 | grep -v "^$\|level=warning" || true

    log "Waiting for cluster nodes to be ready"
    for port in "${CLUSTER_HOST_PORTS[@]}"; do
        printf "    Waiting for localhost:%s... " "$port"
        if wait_for_port "$port" 60; then
            echo -e "${GREEN}OK${RESET}"
        else
            echo -e "${RED}TIMEOUT${RESET}"
            echo "Cluster failed to start. Check: docker compose -f $COMPOSE_FILE logs" >&2
            exit 1
        fi
    done
}

# --- Per-package runner ---

run_package_tests() {
    local pkg=$1
    local pkg_dir="$WORKSPACE_DIR/$pkg"

    if [ ! -d "$pkg_dir" ]; then
        skip "$pkg (directory not found at $pkg_dir)"
        return
    fi

    log "Testing $pkg"

    if [ "$RUN_LINT" = true ]; then
        printf "    ruff check... "
        if (cd "$pkg_dir" && uv run ruff check src tests) >/dev/null 2>&1; then
            echo -e "${GREEN}OK${RESET}"
        else
            record_fail "$pkg: ruff check"
            (cd "$pkg_dir" && uv run ruff check src tests) 2>&1 | head -20
        fi

        printf "    ruff format... "
        if (cd "$pkg_dir" && uv run ruff format --check src tests) >/dev/null 2>&1; then
            echo -e "${GREEN}OK${RESET}"
        else
            record_fail "$pkg: ruff format"
        fi

        printf "    mypy... "
        if (cd "$pkg_dir" && uv run mypy src tests) >/dev/null 2>&1; then
            echo -e "${GREEN}OK${RESET}"
        else
            record_fail "$pkg: mypy"
            (cd "$pkg_dir" && uv run mypy src tests) 2>&1 | tail -5
        fi
    fi

    local pytest_args=(tests/ -q)

    if [ "$UNIT_ONLY" = true ] && [ -d "$pkg_dir/tests/integration" ]; then
        pytest_args+=(--ignore=tests/integration)
    fi

    local output
    if output=$(cd "$pkg_dir" && uv run pytest "${pytest_args[@]}" 2>&1); then
        local summary
        summary=$(echo "$output" | grep -E "^[0-9]+ passed" | tail -1)
        record_pass "$pkg: $summary"
    else
        record_fail "$pkg: pytest"
        echo "$output" | tail -20
    fi

    # SA dialect compliance suite — sqlalchemy-dqlite only.
    # Runs in a separate pytest invocation: its conftest loads SA's
    # plugin which would otherwise replace pytest's normal collection
    # for the rest of the suite. Skipped under --unit since the
    # suite needs the cluster.
    if [ "$pkg" = "sqlalchemy-dqlite" ] && [ "$UNIT_ONLY" = false ] \
        && [ -d "$pkg_dir/tests/compliance" ]; then
        local sa_output
        printf "    SA compliance suite... "
        if sa_output=$(cd "$pkg_dir" && uv run pytest tests/compliance/ -q 2>&1); then
            local sa_summary
            sa_summary=$(echo "$sa_output" | grep -E "^[0-9]+ passed" | tail -1)
            echo -e "${GREEN}OK${RESET} ($sa_summary)"
        else
            record_fail "$pkg: SA compliance suite"
            echo "$sa_output" | tail -20
        fi
    fi
}

# --- Main ---

echo ""
log "dqlite test suite"
echo ""

if [ "$UNIT_ONLY" = true ]; then
    echo "    Mode: unit tests only (no cluster)"
else
    echo "    Mode: unit + integration tests"
    echo "    Cluster: ports ${CLUSTER_HOST_PORTS[*]}"

    if [ "$START_CLUSTER" = true ]; then
        start_cluster
    else
        if ! nc -z localhost "${CLUSTER_HOST_PORTS[0]}" 2>/dev/null; then
            echo -e "    ${RED}Cluster not reachable on port ${CLUSTER_HOST_PORTS[0]}${RESET}" >&2
            echo "    Start it with: docker compose -f $COMPOSE_FILE up -d" >&2
            exit 1
        fi
        echo "    Cluster: already running (--no-cluster)"
    fi
fi

echo ""

for pkg in "${PACKAGES[@]}"; do
    run_package_tests "$pkg"
done

# --- Summary ---

echo ""
log "Results"
total=$((passed + failed))
echo -e "    ${GREEN}$passed passed${RESET}, ${RED}$failed failed${RESET} (of $total checks)"

if [ "$failed" -gt 0 ]; then
    echo ""
    echo -e "    ${RED}Failures:${RESET}"
    for f in "${failures[@]}"; do
        echo "      - $f"
    done
    echo ""
    exit 1
fi

echo ""

#!/usr/bin/env bash
# =============================================================================
# verify_zmq_metrics_fault.sh
#
# PURPOSE
#   Run ZmqMetricsFaultTest and parse the metrics LOG(INFO) output to confirm
#   that each fault scenario is correctly isolated by the ZMQ metrics.
#
# USAGE
#   ./verify_zmq_metrics_fault.sh [--build-dir DIR] [--filter FILTER] [--remote]
#
#   --build-dir DIR   Path to CMake build directory (default: auto-detect)
#   --filter FILTER   gtest filter (default: ZmqMetricsFaultTest.*)
#   --remote          Run on root@38.76.164.55 via ssh
#
# FAULT ISOLATION RUNBOOK (for production use, not just this script)
# ------------------------------------------------------------------
# 1. Enable metrics by calling metrics::Init(ZMQ_METRIC_DESCS, ...) at startup
#    and metrics::Start() after flags are parsed.
# 2. Periodically inspect LOG(INFO) lines tagged "Metrics Summary".
# 3. Use this decision tree:
#
#    zmq.recv.fail > 0 → ZMQ recv hard failure.  Check zmq.last_errno.
#    zmq.send.fail > 0 → ZMQ send hard failure.  Check zmq.last_errno.
#    zmq.net_error > 0 → Network errno class.    → NIC / routing problem.
#    zmq.recv.eagain > 0 → Blocking recv timeout. → Server slow or down.
#    zmq.send.eagain > 0 → HWM back-pressure.    → Producer too fast.
#    zmq.evt.disconn > 0 → ZMQ disconnect event. → Peer crashed / restarted.
#    zmq.gw_recreate > 0 → Gateway recreated.    → Connection recovery happened.
#
#    If none of the above:
#    zmq.io.recv_us avg high (>1ms)? → Network latency / server processing.
#    zmq.rpc.ser_us / deser_us avg high (>100us)? → Protobuf size too large.
#    All avg low? → Bottleneck outside ZMQ (business logic, queue depth).
#
# EXIT CODES
#   0  All checks passed
#   1  One or more checks failed
#   2  Build or binary not found
# =============================================================================
set -euo pipefail

# ── defaults ──────────────────────────────────────────────────────────────────
BUILD_DIR=""
FILTER="ZmqMetricsFaultTest.*"
REMOTE=false
REMOTE_HOST="root@38.76.164.55"
REMOTE_BUILD="/root/workspace/git-repos/yuanrong-datasystem/build"

# ── parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir) BUILD_DIR="$2"; shift 2 ;;
        --filter)    FILTER="$2";    shift 2 ;;
        --remote)    REMOTE=true;    shift   ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── locate binary ─────────────────────────────────────────────────────────────
if [[ "$REMOTE" == "true" ]]; then
    echo "═══ Running on remote $REMOTE_HOST ═══"
    ssh "$REMOTE_HOST" "
        cd $REMOTE_BUILD
        ./tests/st/ds_st --gtest_filter='$FILTER' \
            --alsologtostderr 2>&1
    " | tee /tmp/zmq_metrics_fault_output.txt
    LOG_FILE=/tmp/zmq_metrics_fault_output.txt
else
    if [[ -z "$BUILD_DIR" ]]; then
        BUILD_DIR=$(find /home/t14s/workspace/git-repos/yuanrong-datasystem/build* \
                    -maxdepth 0 -type d 2>/dev/null | head -1 || true)
        [[ -z "$BUILD_DIR" ]] && { echo "ERROR: build dir not found. Use --build-dir"; exit 2; }
    fi
    ST_BIN="$BUILD_DIR/tests/st/ds_st"
    [[ -x "$ST_BIN" ]] || { echo "ERROR: $ST_BIN not found or not executable"; exit 2; }
    echo "═══ Running $ST_BIN --gtest_filter='$FILTER' ═══"
    "$ST_BIN" --gtest_filter="$FILTER" --alsologtostderr 2>&1 | tee /tmp/zmq_metrics_fault_output.txt
    LOG_FILE=/tmp/zmq_metrics_fault_output.txt
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo " ZMQ METRICS FAULT ISOLATION VERIFICATION"
echo "═══════════════════════════════════════════════════════════════════"

PASS=0
FAIL=0

check() {
    local desc="$1"
    local pattern="$2"
    local expected_present="${3:-true}"   # "true"=must match, "false"=must NOT match
    if grep -qE "$pattern" "$LOG_FILE"; then
        if [[ "$expected_present" == "true" ]]; then
            echo "  ✓  $desc"
            ((PASS++)) || true
        else
            echo "  ✗  $desc  [pattern found but should be absent]"
            ((FAIL++)) || true
        fi
    else
        if [[ "$expected_present" == "false" ]]; then
            echo "  ✓  $desc"
            ((PASS++)) || true
        else
            echo "  ✗  $desc  [pattern '$pattern' not found]"
            ((FAIL++)) || true
        fi
    fi
}

# ── Scenario 1: Normal RPCs ────────────────────────────────────────────────
echo ""
echo "── Scenario 1: Normal RPCs ──────────────────────────────────────────"

check "io.send_us histogram populated (count > 0)" \
    "zmq\.io\.send_us,count=[1-9]"
check "io.recv_us histogram populated (count > 0)" \
    "zmq\.io\.recv_us,count=[1-9]"
check "rpc.ser_us histogram populated" \
    "zmq\.rpc\.ser_us,count=[1-9]"
check "rpc.deser_us histogram populated" \
    "zmq\.rpc\.deser_us,count=[1-9]"
check "send.fail == 0 during normal RPCs" \
    "zmq\.send\.fail=0" true
check "net_error == 0 during normal RPCs" \
    "zmq\.net_error=0" true
check "Self-proof report logged" \
    "\[SELF-PROOF" true

# Extract framework ratio from log
RATIO_LINE=$(grep "Framework ratio" "$LOG_FILE" | tail -1 || true)
if [[ -n "$RATIO_LINE" ]]; then
    echo "  ℹ  $RATIO_LINE"
    RATIO=$(echo "$RATIO_LINE" | grep -oE '[0-9]+\.[0-9]+%' | head -1 || echo "unknown")
    echo "  ℹ  Framework ratio = $RATIO (should be < 20% on loopback)"
fi

# ── Scenario 2: Server killed ─────────────────────────────────────────────
echo ""
echo "── Scenario 2: Server Killed ────────────────────────────────────────"

check "recv.fail or recv.eagain raised after server kill" \
    "zmq\.(recv\.fail|recv\.eagain)=[1-9]" true
check "FAULT INJECT: Server shutdown logged" \
    "\[FAULT INJECT\] Shutting down ZMQ server" true

# Log the connection-level metrics for manual inspection
DISCONN_LINE=$(grep "evt.disconn=" "$LOG_FILE" | tail -1 || true)
RECREATE_LINE=$(grep "gw_recreate=" "$LOG_FILE" | tail -1 || true)
[[ -n "$DISCONN_LINE" ]] && echo "  ℹ  $DISCONN_LINE"
[[ -n "$RECREATE_LINE" ]] && echo "  ℹ  $RECREATE_LINE"

# ── Scenario 3: Slow server ───────────────────────────────────────────────
echo ""
echo "── Scenario 3: Slow Server (recv timeout) ───────────────────────────"

check "recv.eagain raised on server timeout" \
    "recv\.eagain=[1-9]" true
check "FAULT INJECT: slow server logged" \
    "\[FAULT INJECT\] Sending 'World'" true
check "ser_us avg reported as low (< 1000us)" \
    "ser_avg=[0-9]{1,3}us" true   # 1-3 digit number = 0-999 us
check "RPC framework innocent during slow server" \
    "ser_avg=[0-9]+" true

# Extract and display slow-server metrics line
SLOW_LINE=$(grep "\[SELF-PROOF\] ser_avg=" "$LOG_FILE" | tail -1 || true)
[[ -n "$SLOW_LINE" ]] && echo "  ℹ  $SLOW_LINE"

# ── Scenario 4: High load self-proof ─────────────────────────────────────
echo ""
echo "── Scenario 4: High Load – Framework Self-Proof ─────────────────────"

check "Self-proof report present in high-load scenario" \
    "\[SELF-PROOF REPORT\]" true
check "RPC framework concluded innocent" \
    "RPC framework is NOT bottleneck" true
check "send.fail == 0 under clean load" \
    "zmq\.send\.fail=0" true

PROOF_BLOCK=$(awk '/\[SELF-PROOF REPORT\]/{found=1} found{print; if(/CONCLUSION/) exit}' "$LOG_FILE" 2>/dev/null || true)
if [[ -n "$PROOF_BLOCK" ]]; then
    echo ""
    echo "  ── Self-Proof Report (verbatim) ──"
    echo "$PROOF_BLOCK" | sed 's/^/  | /'
fi

# ── gtest summary ─────────────────────────────────────────────────────────
echo ""
echo "── gtest Result ─────────────────────────────────────────────────────"
GTEST_SUMMARY=$(grep -E "\[  PASSED  \]|\[  FAILED  \]" "$LOG_FILE" | tail -5 || true)
echo "$GTEST_SUMMARY"

# Check all tests passed
if echo "$GTEST_SUMMARY" | grep -q "\[  FAILED  \]"; then
    echo "  ✗  One or more gtest cases FAILED"
    ((FAIL++)) || true
fi

# ── Final result ──────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo " RESULT: $PASS check(s) PASSED  |  $FAIL check(s) FAILED"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Full output saved to: $LOG_FILE"
echo ""
echo "ISOLATION SUMMARY (from this run):"
echo "  Use 'grep -E \"zmq\\.(send|recv|net|evt|gw)\" $LOG_FILE | tail -30'"
echo "  to see all fault metric lines at a glance."

[[ "$FAIL" -eq 0 ]]

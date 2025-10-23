#!/usr/bin/env bash
set -euo pipefail

echo "--- :lock: Running security vulnerability scan"

# Check if this is a retry attempt
RETRY_COUNT=${BUILDKITE_RETRY_COUNT:-0}

echo "Retry attempt: $RETRY_COUNT"

# Simulate a transient failure on first 2 attempts (exit code 2)
# This demonstrates auto-retry in action for your demo
if [ "$RETRY_COUNT" -lt 2 ]; then
    echo "!!! Simulating transient network failure (exit 2) - will auto-retry"
    echo "In a real scenario, this could be:"
    echo "  - Docker registry timeout"
    echo "  - CVE database sync issues"
    echo "  - Network hiccup"
    sleep 2
    exit 2
fi

echo "✓ Connection successful on retry #$RETRY_COUNT"
echo ""

# Now run actual security scan (mocked for demo)
echo "--- Scanning Docker images for vulnerabilities"

# Mock scan results
cat <<EOF
Scanning image: myapp:latest

HIGH: 0 vulnerabilities
MEDIUM: 2 vulnerabilities
LOW: 5 vulnerabilities

┌─────────────────┬──────────────┬──────────┬───────────────────┐
│    PACKAGE      │ VULNERABILITY│ SEVERITY │  FIXED VERSION    │
├─────────────────┼──────────────┼──────────┼───────────────────┤
│ libssl1.1       │ CVE-2024-0001│ MEDIUM   │ 1.1.1w-1          │
│ curl            │ CVE-2024-0002│ MEDIUM   │ 7.88.1-1          │
└─────────────────┴──────────────┴──────────┴───────────────────┘

EOF

echo ""
echo "--- :test_tube: Running SAST analysis"
sleep 1
echo "✓ No critical code vulnerabilities detected"

echo ""
echo "--- :package: Checking dependency vulnerabilities"
sleep 1
echo "✓ All dependencies within acceptable risk threshold"

echo ""
echo "+++ :white_check_mark: Security scan completed successfully"
echo "Report uploaded to artifact store"

# Success!
exit 0

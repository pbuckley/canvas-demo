#!/usr/bin/env bash
set -euo pipefail

echo "--- :npm: npm ci"
echo ""
echo "added 342 packages, and audited 343 packages in 8s"
echo ""
echo "78 packages are looking for funding"
echo "  run \`npm fund\` for details"
echo ""
echo "found 0 vulnerabilities"
sleep 2

echo ""
echo "--- :webpack: npm run build"
echo ""
echo "> myapp@2.1.4 build"
echo "> webpack --mode production"
echo ""
echo "asset main.js 127 KiB [emitted] [minimized] (name: main) 1 related asset"
echo "asset vendors.bundle.js 89.3 KiB [emitted] [minimized] (name: vendors)"
echo "asset styles.css 24.1 KiB [emitted] (name: main)"
echo "runtime modules 3.76 KiB 9 modules"
echo "cacheable modules 487 KiB"
echo "  modules by path ./src/ 234 KiB"
echo "    ./src/index.js 3.21 KiB [built] [code generated]"
echo "    ./src/components/ 156 KiB [built] [code generated]"
echo "    ./src/utils/ 47.2 KiB [built] [code generated]"
echo "    ./src/styles/ 27.6 KiB [built] [code generated]"
echo "  modules by path ./node_modules/ 253 KiB"
echo "    ./node_modules/react/ 89.4 KiB [built] [code generated]"
echo "    ./node_modules/react-dom/ 163 KiB [built] [code generated]"
sleep 2
echo ""
echo "webpack 5.89.0 compiled successfully in 4832 ms"

# Create mock artifacts
mkdir -p dist
echo "Mock bundled JS" > dist/main.js
echo "Mock CSS" > dist/styles.css

echo ""
echo "--- :jest: npm test"
echo ""
echo "> myapp@2.1.4 test"
echo "> jest"
echo ""
echo " PASS  src/components/Header.test.js"
echo "  Header Component"
echo "    ✓ renders header title (23 ms)"
echo "    ✓ displays user menu when logged in (18 ms)"
echo "    ✓ hides user menu when logged out (12 ms)"
echo ""
echo " PASS  src/components/Dashboard.test.js"
echo "  Dashboard Component"
echo "    ✓ loads and displays metrics (45 ms)"
echo "    ✓ handles empty state (8 ms)"
echo "    ✓ refreshes data on button click (31 ms)"
echo ""
echo " PASS  src/utils/formatter.test.js"
echo "  Formatter Utils"
echo "    ✓ formats currency correctly (5 ms)"
echo "    ✓ formats dates in ISO format (4 ms)"
echo "    ✓ handles null values gracefully (3 ms)"
echo ""
sleep 1
echo "Test Suites: 3 passed, 3 total"
echo "Tests:       9 passed, 9 total"
echo "Snapshots:   0 total"
echo "Time:        3.847 s"
echo "Ran all test suites."

echo ""
echo "+++ :white_check_mark: Node.js build and tests completed"

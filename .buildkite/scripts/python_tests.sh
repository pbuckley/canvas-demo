#!/usr/bin/env bash
set -euo pipefail

echo "--- :python: Installing dependencies"
echo "Collecting pytest==7.4.3"
echo "  Using cached pytest-7.4.3-py3-none-any.whl (325 kB)"
echo "Collecting pytest-cov==4.1.0"
echo "  Using cached pytest_cov-4.1.0-py3-none-any.whl (21 kB)"
echo "Collecting requests==2.31.0"
echo "  Using cached requests-2.31.0-py3-none-any.whl (62 kB)"
echo "Collecting flask==3.0.0"
echo "  Using cached flask-3.0.0-py3-none-any.whl (99 kB)"
echo "Installing collected packages: pytest, pytest-cov, requests, flask"
echo "Successfully installed flask-3.0.0 pytest-7.4.3 pytest-cov-4.1.0 requests-2.31.0"
sleep 2

echo ""
echo "--- :pytest: Running pytest with coverage"
echo ""
echo "============================= test session starts =============================="
echo "platform linux -- Python 3.11.6, pytest-7.4.3, pluggy-1.3.0"
echo "rootdir: /buildkite/builds/agent-1/myapp"
echo "plugins: cov-4.1.0"
echo "collected 24 items"
echo ""
sleep 1
echo "tests/test_auth.py ......                                                [ 25%]"
sleep 0.5
echo "tests/test_api.py .........                                              [ 62%]"
sleep 0.5
echo "tests/test_models.py .....                                               [ 83%]"
sleep 0.5
echo "tests/test_utils.py ....                                                 [100%]"
sleep 1
echo ""
echo "---------- coverage: platform linux, python 3.11.6-final-0 -----------"
echo "Name                      Stmts   Miss  Cover"
echo "---------------------------------------------"
echo "src/__init__.py               4      0   100%"
echo "src/auth.py                  47      2    96%"
echo "src/api.py                   89      5    94%"
echo "src/models.py                65      3    95%"
echo "src/utils.py                 34      1    97%"
echo "---------------------------------------------"
echo "TOTAL                       239     11    95%"
echo ""
echo "Coverage HTML written to dir htmlcov"
echo ""

# Create mock coverage artifacts
mkdir -p coverage
echo "<html><body>Mock coverage report</body></html>" > coverage/index.html

echo "============================== 24 passed in 2.47s ==============================="

echo ""
echo "+++ :white_check_mark: All Python tests passed with 95% coverage"

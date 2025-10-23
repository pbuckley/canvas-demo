#!/usr/bin/env bash
set -euo pipefail

echo "--- :maven: Maven Clean Package"
echo "[INFO] Scanning for projects..."
sleep 1
echo "[INFO] "
echo "[INFO] ----------------< com.example:myapp >----------------"
echo "[INFO] Building MyApp 1.0.0"
echo "[INFO] --------------------------------[ jar ]---------------------------------"
echo "[INFO] "
echo "[INFO] --- maven-clean-plugin:3.2.0:clean (default-clean) @ myapp ---"
echo "[INFO] Deleting target"
sleep 1
echo "[INFO] "
echo "[INFO] --- maven-resources-plugin:3.3.0:resources (default-resources) @ myapp ---"
echo "[INFO] Copying 15 resources"
echo "[INFO] "
echo "[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) @ myapp ---"
echo "[INFO] Compiling 47 source files to target/classes"
sleep 2
echo "[INFO] "
echo "[INFO] --- maven-resources-plugin:3.3.0:testResources (default-testResources) @ myapp ---"
echo "[INFO] Copying 8 resources"
echo "[INFO] "
echo "[INFO] --- maven-compiler-plugin:3.11.0:testCompile (default-testCompile) @ myapp ---"
echo "[INFO] Compiling 23 test source files to target/test-classes"
sleep 1
echo "[INFO] "
echo "[INFO] --- maven-surefire-plugin:3.0.0:test (default-test) @ myapp ---"
echo "[INFO] "
echo "[INFO] -------------------------------------------------------"
echo "[INFO]  T E S T S"
echo "[INFO] -------------------------------------------------------"
echo "[INFO] Running com.example.myapp.UserServiceTest"
echo "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.842 s"
echo "[INFO] Running com.example.myapp.PaymentServiceTest"
echo "[INFO] Tests run: 8, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 1.123 s"
echo "[INFO] "
echo "[INFO] Results:"
echo "[INFO] "
echo "[INFO] Tests run: 13, Failures: 0, Errors: 0, Skipped: 0"
echo "[INFO] "
sleep 1
echo "[INFO] --- maven-jar-plugin:3.3.0:jar (default-jar) @ myapp ---"
echo "[INFO] Building jar: target/myapp-1.0.0.jar"
echo "[INFO] "
echo "[INFO] ------------------------------------------------------------------------"
echo "[INFO] BUILD SUCCESS"
echo "[INFO] ------------------------------------------------------------------------"
echo "[INFO] Total time:  12.456 s"
echo "[INFO] Finished at: $(date -Iseconds)"
echo "[INFO] ------------------------------------------------------------------------"

# Create mock artifact
mkdir -p target
echo "Mock JAR file" > target/myapp-1.0.0.jar

echo ""
echo "+++ :white_check_mark: Java build completed successfully"

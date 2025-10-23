#!/usr/bin/env bash
set -euo pipefail

PIPELINE=${BUILDKITE_PIPELINE_SLUG:-demo-pipeline}
BUILD=${BUILDKITE_BUILD_NUMBER:-123}

echo "--- :buildkite: Downloading artifacts"
echo ""
echo "Downloading artifacts from previous steps..."
sleep 1
echo "  target/myapp-1.0.0.jar (2.4 MB) ✓"
echo "  dist/main.js (127 KB) ✓"
echo "  dist/styles.css (24 KB) ✓"
echo "  app/build/outputs/apk/debug/app-debug.apk (8.4 MB) ✓"
echo "  coverage/index.html (156 KB) ✓"
echo ""
echo "Downloaded 5 artifacts (11.1 MB)"

echo ""
echo "--- :s3: Uploading to S3"
echo ""
echo "Syncing to s3://my-buildkite-artifacts/$PIPELINE/$BUILD/"
sleep 1
echo "upload: artifacts/target/myapp-1.0.0.jar to s3://my-buildkite-artifacts/$PIPELINE/$BUILD/target/myapp-1.0.0.jar"
sleep 0.5
echo "upload: artifacts/dist/main.js to s3://my-buildkite-artifacts/$PIPELINE/$BUILD/dist/main.js"
sleep 0.3
echo "upload: artifacts/dist/styles.css to s3://my-buildkite-artifacts/$PIPELINE/$BUILD/dist/styles.css"
sleep 0.5
echo "upload: artifacts/app/build/outputs/apk/debug/app-debug.apk to s3://my-buildkite-artifacts/$PIPELINE/$BUILD/apk/app-debug.apk"
sleep 0.4
echo "upload: artifacts/coverage/index.html to s3://my-buildkite-artifacts/$PIPELINE/$BUILD/coverage/index.html"
sleep 0.5
echo ""
echo "Uploaded 5 files (11.1 MB) in 2.3s"
echo ""
echo "+++ :white_check_mark: All artifacts uploaded to S3"
echo "Bucket: my-buildkite-artifacts"
echo "Path: $PIPELINE/$BUILD/"
echo "Region: $AWS_DEFAULT_REGION"
echo "URL: https://my-buildkite-artifacts.s3.$AWS_DEFAULT_REGION.amazonaws.com/$PIPELINE/$BUILD/"

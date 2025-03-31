#!/usr/bin/env bash

echo "+++ try some curl with our see c r at"

export BK_API_TOKEN=$(buildkite-agent secret get readtokenpb)

curl -H "Authorization\: Bearer ${BK_API_TOKEN}" -X GET "https\://api.buildkite.com/v2/organizations/demo/pipelines/service-foo/builds"

echo "--- done the try of curly q"

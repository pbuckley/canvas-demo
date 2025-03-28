#!/usr/bin/env bash

export REXITCODE=$((0 + $RANDOM % 4))
echo "+++ Generate a random exit code between 1-4, this time its ${REXITCODE}"
exit ${REXITCODE}


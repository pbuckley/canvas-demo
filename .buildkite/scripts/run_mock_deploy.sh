#!/usr/bin/env bash

echo "+++ Generate a random exit code between 1-4"
exit $((0 + $RANDOM % 4))

#!/usr/bin/env bash
# Explicit foreground serial suite, not an overnight/background launch.
set -euo pipefail
llm_all_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 -u -B "$llm_all_here/transformer/suite.py" "$@"

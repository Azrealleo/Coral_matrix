#!/usr/bin/env bash
# Explicit next-day simulation entry. NEVER called by prepare_tomorrow.sh.
set -euo pipefail
opt_here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if [[ $# -ne 2 ]]; then echo 'Usage: run_vm.sh PREPARED_DIRECTORY quick|all|probe|0|1|2|3' >&2;exit 2;fi
opt_prepared=$(cd -- "$1" && pwd -P)
unset WAVES GUI COCOTB_ENABLE_PROFILING COCOTB_TESTCASE COCOTB_TEST_FILTER
export PYTHONDONTWRITEBYTECODE=1
case "$2" in
  quick|all) python3 -u -B "$opt_here/vm.py" sequence --allow-rtl-simulation --prepared "$opt_prepared" --plan "$2";;
  probe) python3 -u -B "$opt_here/vm.py" run --allow-rtl-simulation --prepared "$opt_prepared" --case 4;;
  0|1|2|3) python3 -u -B "$opt_here/vm.py" run --allow-rtl-simulation --prepared "$opt_prepared" --case "$2";;
  *) echo 'Unknown plan/case; nothing started.' >&2;exit 2;;
esac

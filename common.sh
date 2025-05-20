#!/usr/bin/env bash

set -euo pipefail
shopt -s nullglob 

: "${QEXEC:?Error: QEXEC not set. Probably skipped sourcing config/kdbenv}"

function die () {
  local msg="$1"
  local code="${2:-1}"
  echo "ERROR: $msg" >&2
  return "$code" 2>/dev/null || exit "$code"
}

if [[ $# -lt 1 ]]; then
  die "ERROR: Missing required argument - data directory" 1
fi

readonly DATADIR="$1"
readonly CSVDIR=$DATADIR/raw
readonly DST=$DATADIR/tq

readonly CORECOUNT=$(nproc)
readonly CPUSOCKETNR=$(cat /proc/cpuinfo | grep "physical id" | sort -u | wc -l)

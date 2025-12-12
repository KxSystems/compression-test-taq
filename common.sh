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

function get_date () {
  local date="${1:-$(date +"%Y%m%d")}"
  if ! [[ "$date" =~ ^[0-9]{8}$ ]]; then
    die "Error: DATE must be in YYYYMMDD format. Got: '$date'" 1
  fi
  echo $date
}

if [[ $# -lt 1 ]]; then
  die "ERROR: Missing required argument - data directory" 1
fi

readonly DATADIR="$1"
readonly CSVDIR=$DATADIR/raw
readonly DSTKDB=$DATADIR/tq
readonly DSTPARQUET=$DATADIR/parquet

if [[ $(uname) == "Linux" ]]; then
    SOCKETNR=$(lscpu | grep "Socket(s)" | cut -d":" -f 2 |xargs)
    COREPERSOCKET=$(lscpu | grep "Core(s) per socket" | cut -d":" -f 2 |xargs)
    THREADPERCORE=$(lscpu | grep "Thread(s) per core" | cut -d":" -f 2 |xargs)
else
    SOCKETNR=1
    COREPERSOCKET=$(sysctl -n hw.ncpu)
    THREADPERCORE=1
fi
COMPUTECOUNT=$((COREPERSOCKET * SOCKETNR * THREADPERCORE))


readonly VALID_SIZES=("full" "large" "medium" "small")

: "${SIZE:?Error: SIZE must be set to 'full', 'large', 'medium', or 'small'}"

if [[ ! " ${VALID_SIZES[*]} " =~ " ${SIZE} " ]]; then
    die "Error: Unknown SIZE: $SIZE. Valid options are: ${VALID_SIZES[*]}" 1
fi

case "$SIZE" in
  "full")   LETTERS='A-Z' ;;
  "large")  LETTERS='A-H' ;;
  "medium") LETTERS='I-I' ;;
  "small")  LETTERS='Z-Z' ;;
esac
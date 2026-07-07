#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

readonly CSVDIR="$1"
readonly DST="$2"
readonly DATE=$(get_date $3)

function generate_HDB () {
  LETTERS=$(get_letters $SIZE)

  if [[ ${DATAFORMAT} == "parquet" ]]; then
    echo "Generating parquet dataset..."
    python3 ./pysrc/taq_to_parquet.py -date $DATE -src $CSVDIR -dst $DST -letters $LETTERS
  else
    check_kdb
    echo "Generating kdb+ data (aka. HDB)..."
    $QEXEC ./src/taqToKDB.q -date $DATE -src $CSVDIR -dst $DST -letters $LETTERS -s $(nproc) -q
  fi
}

generate_HDB

#!/usr/bin/env bash

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/common.sh"

readonly CSVDIR="$1"
readonly DST="$2"
readonly DATE=$(get_date $3)

function generate_HDB () {
  if [[ ${DATAFORMAT} == "parquet" ]]; then
    echo "Generating parquet dataset..."
    python3 ./pysrc/taq_to_parquet.py -date $DATE -src $CSVDIR -dst $DST -letters $LETTERS
  else
    echo "Generating kdb+ data (aka. HDB)..."
    $QEXEC ./src/taqToKDB.q -date $DATE -src $CSVDIR -dst $DST -batchsize ${KDBBATCHSIZE} -letters $LETTERS -s ${KDBTHREADNR} -q
  fi
}

generate_HDB

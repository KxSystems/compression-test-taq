#!/usr/bin/env bash

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/common.sh"

readonly DATE=$(get_date $2)

function generate_HDB () {
  if [[ ${DATAFORMAT} == "parquet" ]]; then
    echo "Generating parquet dataset..."
    python3 ./pysrc/taq_to_parquet.py -date $DATE -src $CSVDIR -dst $DSTPARQUET/uncompressed -letters $LETTERS
  else
    echo "Generating kdb+ data (aka. HDB)..."
    $QEXEC ./src/taqToKDB.q -date $DATE -src $CSVDIR -dst $DSTKDB/zd0_0_0 -letters $LETTERS -s $COMPUTECOUNT -q
  fi
}

function cleanup_CSVs () {
  rm -rf ${CSVDIR}
}

generate_HDB
cleanup_CSVs

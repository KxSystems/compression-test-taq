#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

THREAD_NRS=()
RESULT_DIR="./results"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -c, --csv-dir      Directory containing source CSV files
  --db-dir           Directory where databases will be generated
  -p, --param-dir    Directory of the query parameters
  -d, --date         Target date
  -t, --threads      Space-separated list of thread counts (e.g., "1 2 4")
  -r, --result-dir   Directory for query results
  -h, --help         Show this help message
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--csv-dir)    CSV_DIR="$2"; shift 2 ;;
        --db-dir)        DB_DIR="$2"; shift 2 ;;
        -p|--param-dir)  PARAM_DIR="$2"; shift 2 ;;
        -d|--date)       RAW_DATE="$2"; shift 2 ;;
        -t|--threads)    read -ra THREAD_NRS <<< "$2"; shift 2 ;;
        -r|--result-dir) RESULT_DIR="$2"; shift 2 ;;
        -h|--help)    usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

readonly DATE=$(get_date "$RAW_DATE")

function generate_data () {
    echo "Generating Databases..."
    # Step 1: We assume that the CSV files are already downloaded
    # Step 2: generate data from CSV files
    DATAFORMAT=kdb ./generateDB.sh ${CSV_DIR} ${DB_DIR}/kdb${DATE}
    SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet ./generateDB.sh ${CSV_DIR} ${DB_DIR}/parquet/rowgroup ${DATE}
}

function get_numa_config () {
    if [[ -z "${NUMANODE:-}" ]]; then
        echo ""
        return
    fi

    echo "numactl -N ${NUMANODE} -m ${NUMANODE}"
}
function execute_queries () {
    mkdir -p ${RESULT_DIR}
    echo "Running Queries..."
    for s in "${THREAD_NRS[@]}"; do
        echo "--> Running with $s threads"
        $(get_numa_config) $QEXEC ./src/runQueries.q -db ${DB_DIR}/kdb-format kdb -queryfile ./artifacts/queries/kdb.psv -paramdir ${PARAM_DIR} -result ${RESULT_DIR}/kdb_kdb_${s}Threads.psv -s ${s}
        QMAP=TRUE $(get_numa_config) $QEXEC ./src/runQueries.q -db ${DB_DIR}/kdb-format kdb -queryfile ./artifacts/queries/kdb_peach.psv -paramdir ${PARAM_DIR} -result ${RESULT_DIR}/kdbPeachQMAP_kdb_${s}Threads.psv -s ${s}
        $(get_numa_config) $QEXEC ./src/runQueries.q -db ${DB_DIR}/parquet/rowgroup -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ${PARAM_DIR} -result ${RESULT_DIR}/kdb_parquetRowgroup_${s}Threads.psv -s ${s}

        POLARS_MAX_THREADS=$s $(get_numa_config) python3 pysrc/run_queries.py -engine polars -db ${DB_DIR}/parquet/rowgroup -queryfile ./artifacts/queries/polars.psv -paramdir ${PARAM_DIR} -result ${RESULT_DIR}/polars_parquetRowgroup_${s}Threads.psv
        QARGS="-s ${s}" $(get_numa_config) python3 pysrc/run_queries.py -engine pykx -db ${DB_DIR}/kdb-queryfile ./artifacts/queries/pykx.psv -paramdir ${PARAM_DIR} -result ${RESULT_DIR}/pykx_kdb_${s}Threads.psv
        QARGS="-s ${s}" $(get_numa_config) python3 pysrc/run_queries.py -engine pykxq -db ${DB_DIR}/kdb-queryfile ./artifacts/queries/kdb.psv -paramdir ${PARAM_DIR} -result ${RESULT_DIR}/pykxq_kdb_${s}Threads.psv
    done
}

generate_data
execute_queries

echo "Benchmark suite complete."
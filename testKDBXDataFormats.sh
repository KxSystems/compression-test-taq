#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

THREAD_NRS=(1 4)
RESULT_DIR="./results"
SCOPE="ondisk"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -c, --csv-dir      Directory containing source CSV files
  --db-dir           Directory where databases will be generated
  -p, --param-dir    Directory of the query parameters
  -d, --date         Target date
  -t, --threads      Space-separated list of thread counts, e.g., "1 4 16", (default: "1 4")
  -r, --result-dir   Directory for query results (default: ./results)
  -s, --scope        Scope of the test, e.g. ondisk, inmem (default: ondisk)
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
        -s|--scope)      SCOPE="$2"; shift 2 ;;
        -h|--help)    usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

readonly DATE=$(get_date "$RAW_DATE")

function generate_data () {
    echo "Generating Databases..."
    # Step 1: We assume that the CSV files are already downloaded
    # Step 2: generate data from CSV files
    DATAFORMAT=kdb ./generateDB.sh ${CSV_DIR} ${DB_DIR}/kdb ${DATE}
    SYMBOLSTOREDAS=PartitionColumn DATAFORMAT=parquet ./generateDB.sh ${CSV_DIR} ${DB_DIR}/parquet/hivepartitioned ${DATE}
    SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet ./generateDB.sh ${CSV_DIR} ${DB_DIR}/parquet/rowgroup ${DATE}
    # SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet MINROWGROUPSIZE=100000 ./generateDB.sh ${CSV_DIR} ${DB_DIR}/parquet/rowgroup_minrowgroup_100000 ${DATE}
    SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet MAXROWGROUPSIZE=250000 ./generateDB.sh ${CSV_DIR} ${DB_DIR}/parquet/rowgroup_maxrowgroupsize250000 ${DATE}
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
    local COMMONPARAMS="-querymeta ./artifacts/queries/querymeta.psv -paramdir ${PARAM_DIR}"
    for s in "${THREAD_NRS[@]}"; do
        echo "--> Running with $s threads"
        if [[ "${SCOPE}" == *"ondisk"* ]]; then
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdb -queryfile ./artifacts/queries/kdb.psv -result ${RESULT_DIR}/kdb_${s}Threads.psv -s ${s}
            QMAP=TRUE $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdb -queryfile ./artifacts/queries/kdb_peach.psv -result ${RESULT_DIR}/kdbPeachQMAP_${s}Threads.psv -s ${s}

            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/parquet/hivepartitioned -format parquet -queryfile ./artifacts/queries/parquet_partition.psv -result ${RESULT_DIR}/parquetHivePartitioned_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/parquet/hivepartitioned -format parquet -queryfile ./artifacts/queries/parquet_partition_peach.psv -result ${RESULT_DIR}/parquetHivePartitionedPeach_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/parquet/rowgroup -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -result ${RESULT_DIR}/parquetRowgroup_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/parquet/rowgroup -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup_peach.psv -result ${RESULT_DIR}/parquetRowgroupPeach_${s}Threads.psv -s ${s}
            # $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/parquet/rowgroup_minrowgroup_100000 -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -result ${RESULT_DIR}/parquetRowgroupMinSize_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/parquet/rowgroup_maxrowgroupsize250000 -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -result ${RESULT_DIR}/parquetRowgroupMaxSize_${s}Threads.psv -s ${s}
        fi

        if [[ "${SCOPE}" == *"inmem"* ]]; then
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdbinmemory -queryfile ./artifacts/queries/kdb_inmemory.psv -result ${RESULT_DIR}/kdbInMemory_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdbinmemorygroupped -queryfile ./artifacts/queries/kdb_inmemory.psv -result ${RESULT_DIR}/kdbInMemoryGroupped_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdbinmemorytabledict -queryfile ./artifacts/queries/kdb_inmemory_tabledict.psv -result ${RESULT_DIR}/kdbInMemoryTableDict_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdbinmemorygroupped -engine sql -queryfile ./artifacts/queries/sql_inmemory.psv -result ${RESULT_DIR}/sqlInMemoryGroupped_${s}Threads.psv -s ${s}
            EACHPEACH=peach $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -db ${DB_DIR}/kdb -format kdbinmemorytabledict -queryfile ./artifacts/queries/kdb_inmemory_tabledict.psv -result ${RESULT_DIR}/kdbInMemoryTableDictPeach_${s}Threads.psv -s ${s}
            POLARS_MAX_THREADS=$(( s > 1 ? s : 1 )) $(get_numa_config) python3 pysrc/run_queries.py ${COMMONPARAMS} -db ${DB_DIR}/parquet/rowgroup -engine polars_inmemory -queryfile ./artifacts/queries/polars_inmemory.psv -result ${RESULT_DIR}/polarsInMemory_${s}Threads.psv
            QARGS="-s ${s}" $(get_numa_config) python3 pysrc/run_queries.py -engine pykx_inmemory -db ${DB_DIR}/kdb -queryfile ./artifacts/queries/pykx_inmemory.psv ${COMMONPARAMS} -result ${RESULT_DIR}/pykx_inmemory_kdb_${s}Threads.psv
        fi
    done
}

generate_data
execute_queries

echo "Benchmark suite complete."
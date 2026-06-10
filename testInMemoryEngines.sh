#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

THREAD_NRS=(1 4)
RESULT_DIR="./results"
STATS_DIR="./stats"
ENGINES="kdb,sql,duckdb,polars,pykx,pandas"
IDX_PARAM=""

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --db-dir           Directory where databases will be generated
  -p, --param-dir    Directory of the query parameters
  -d, --date         Target date
  -t, --threads      Space-separated list of thread counts, e.g., "1 4 16", (default: "1 4")
  -r, --result-dir   Directory for query results (default: ./results)
  -e, --engines      Comma-separated list of engines to test (default: "kdb,sql,duckdb,polars,pykx,pandas")
  -i, --idx          Filter queries by index: single (42), list (32,42,50), or range (40-44)
  -h, --help         Show this help message
  --stats-dir        Directory to save table stats (default: ./stats)
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --db-dir)        DB_DIR="$2"; shift 2 ;;
        -p|--param-dir)  PARAM_DIR="$2"; shift 2 ;;
        -d|--date)       RAW_DATE="$2"; shift 2 ;;
        -t|--threads)    read -ra THREAD_NRS <<< "$2"; shift 2 ;;
        -r|--result-dir) RESULT_DIR="$2"; shift 2 ;;
        -e|--engines)    ENGINES="$2"; shift 2 ;;
        --stats-dir)     STATS_DIR="$2"; shift 2 ;;
        -i|--idx)        IDX_PARAM="-idx $2"; shift 2 ;;
        -h|--help)    usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

readonly DATE=$(get_date "$RAW_DATE")

function engine_enabled() {
    [[ ",${ENGINES}," == *",${1},"* ]]
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
    local COMMONPARAMS="-querymeta ./artifacts/queries/querymeta.psv -paramdir ${PARAM_DIR} ${IDX_PARAM}"
    for s in "${THREAD_NRS[@]}"; do
        echo "--> Running with $s threads"

        if engine_enabled kdb; then
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorynoattr -queryfile ./artifacts/queries/inmemory/kdb.psv -result ${RESULT_DIR}/kdbInMemoryNoAttr_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemory -queryfile ./artifacts/queries/inmemory/kdb.psv -result ${RESULT_DIR}/kdbInMemory_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorygrouped -queryfile ./artifacts/queries/inmemory/kdb_grouped.psv -result ${RESULT_DIR}/kdbInMemoryGrouped_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemoryparted -queryfile ./artifacts/queries/inmemory/kdb_grouped.psv -result ${RESULT_DIR}/kdbInMemoryParted_${s}Threads.psv -s ${s}
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorytabledict -queryfile ./artifacts/queries/inmemory/kdb_tabledict.psv -result ${RESULT_DIR}/kdbInMemoryTableDict_${s}Threads.psv -s ${s}
            EACHPEACH=peach $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorytabledict -queryfile ./artifacts/queries/inmemory/kdb_tabledict.psv -result ${RESULT_DIR}/kdbInMemoryTableDictPeach_${s}Threads.psv -s ${s}
        fi
        if engine_enabled sql; then
            $(get_numa_config) $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorygrouped -engine sql -queryfile ./artifacts/queries/inmemory/sql.psv -result ${RESULT_DIR}/sqlInMemoryGrouped_${s}Threads.psv -s ${s}
        fi
        if engine_enabled duckdb; then
            DUCKDB_THREADS=$(( s > 1 ? s : 1 )) $(get_numa_config) python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine duckdb_con_inmemory -queryfile ./artifacts/queries/inmemory/duckdb.psv -result ${RESULT_DIR}/duckdbInMemory_${s}Threads.psv
            DUCKDB_THREADS=$(( s > 1 ? s : 1 )) $(get_numa_config) python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine duckdb_con_inmemory_symtimesort -queryfile ./artifacts/queries/inmemory/duckdb.psv -result ${RESULT_DIR}/duckdbInMemorySymTimeSort_${s}Threads.psv
            DUCKDB_THREADS=$(( s > 1 ? s : 1 )) $(get_numa_config) python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine duckdb_con_inmemory_index -queryfile ./artifacts/queries/inmemory/duckdb.psv -result ${RESULT_DIR}/duckdbInMemoryIndex_${s}Threads.psv
        fi
        if engine_enabled polars; then
            POLARS_MAX_THREADS=$(( s > 1 ? s : 1 )) $(get_numa_config) python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine polars_inmemory -queryfile ./artifacts/queries/inmemory/polars.psv -result ${RESULT_DIR}/polarsInMemory_${s}Threads.psv
        fi
        if engine_enabled pykx; then
            QARGS="-s ${s}" $(get_numa_config) python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -engine pykx_inmemory -queryfile ./artifacts/queries/inmemory/pykx.psv -result ${RESULT_DIR}/pykx_kdb_${s}Threads.psv
        fi
        if engine_enabled pandas; then
            OMP_NUM_THREADS=$(( s > 1 ? s : 1 )) NUMEXPR_NUM_THREADS=$(( s > 1 ? s : 1 )) MKL_NUM_THREADS=$(( s > 1 ? s : 1 )) $(get_numa_config) python3 pysrc/run_queries.py -engine pandas -date $DATE -db ${DB_DIR}/parquet/rowgroup -queryfile ./artifacts/queries/inmemory/pandas.psv ${COMMONPARAMS} -result ${RESULT_DIR}/pandasInMemory_${s}Threads.psv
        fi
    done
}

function get_table_stats () {
    local COMMONPARAMS="-querymeta ./artifacts/queries/querymeta.psv -paramdir ${PARAM_DIR} ${IDX_PARAM}"
    echo "Getting table stats..."
    mkdir -p ${STATS_DIR}/inmemory/{kdb_noattr,kdb,kdb_grouped,kdb_parted,kdb_tabledict,duckdb,duckdb_index,polars,pandas}
    if engine_enabled kdb; then
        /usr/bin/time -v $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorynoattr -queryfile ./artifacts/queries/inmemory/kdb.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/kdb_noattr -q 2> ${STATS_DIR}/inmemory/kdb_noattr/os.txt
        /usr/bin/time -v $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemory -queryfile ./artifacts/queries/inmemory/kdb.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/kdb -q 2> ${STATS_DIR}/inmemory/kdb/os.txt
        /usr/bin/time -v $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorygrouped -queryfile ./artifacts/queries/inmemory/kdb_grouped.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/kdb_grouped -q 2> ${STATS_DIR}/inmemory/kdb_grouped/os.txt
        /usr/bin/time -v $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemoryparted -queryfile ./artifacts/queries/inmemory/kdb_grouped.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/kdb_parted -q 2> ${STATS_DIR}/inmemory/kdb_parted/os.txt
        /usr/bin/time -v $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorytabledict -queryfile ./artifacts/queries/inmemory/kdb_tabledict.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/kdb_tabledict -q 2> ${STATS_DIR}/inmemory/kdb_tabledict/os.txt
    fi
    if engine_enabled sql; then # same as kdb+ inmemory grouped
        /usr/bin/time -v $QEXEC ./src/runQueries.q ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/kdb -format kdbinmemorygrouped -queryfile ./artifacts/queries/inmemory/kdb_grouped.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/kdb_grouped -q 2> ${STATS_DIR}/inmemory/kdb_grouped/os.txt
    fi
    if engine_enabled duckdb; then
        /usr/bin/time -v python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine duckdb_con_inmemory -queryfile ./artifacts/queries/inmemory/duckdb.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/duckdb 2> ${STATS_DIR}/inmemory/duckdb/os.txt
        /usr/bin/time -v python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine duckdb_con_inmemory_index -queryfile ./artifacts/queries/inmemory/duckdb.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/duckdb_index 2> ${STATS_DIR}/inmemory/duckdb_index/os.txt
    fi
    if engine_enabled polars; then
        /usr/bin/time -v python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine polars_inmemory -queryfile ./artifacts/queries/inmemory/polars.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/polars 2> ${STATS_DIR}/inmemory/polars/os.txt
    fi
    if engine_enabled pandas; then
        /usr/bin/time -v python3 pysrc/run_queries.py ${COMMONPARAMS} -date $DATE -db ${DB_DIR}/parquet/rowgroup -engine pandas -queryfile ./artifacts/queries/inmemory/pandas.psv -tags none -tableStatsDir ${STATS_DIR}/inmemory/pandas 2> ${STATS_DIR}/inmemory/pandas/os.txt
    fi
}

execute_queries
get_table_stats

echo "Benchmark suite complete."
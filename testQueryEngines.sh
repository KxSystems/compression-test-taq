#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

readonly CSVDIR=$1
readonly DBDIR=$2
readonly DATE=$(get_date $3)
readonly RESULTDIR=$4

# Step 1: We assume that the CSV files are already downloaded
# Step 2: generate data from CSV files
DATAFORMAT=kdb ./generateDB.sh ${CSVDIR} ${DBDIR}/kdb/${SIZE} ${DATE}
SYMBOLSTOREDAS=PartitionColumn DATAFORMAT=parquet ./generateDB.sh ${CSVDIR} ${DBDIR}/parquet/${SIZE}/hivepartitioned ${DATE}
SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet ./generateDB.sh ${CSVDIR} ${DBDIR}/parquet/${SIZE}/rowgroup ${DATE}
SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet MINROWGROUPSIZE=100000 ./generateDB.sh ${CSVDIR} ${DBDIR}/parquet/${SIZE}/rowgroup_minrowgroup_100000 ${DATE}
SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet MAXROWGROUPSIZE=250000 ./generateDB.sh ${CSVDIR} ${DBDIR}/parquet/${SIZE}/rowgroup_maxrowgroupsize250000 ${DATE}


# Step 3: Generate query parameters
$QEXEC ./artifacts/parameters/genParameters.q -db ${DBDIR}/kdb/${SIZE}/ -dst ./artifacts/parameters/${SIZE}

# Step 4: Run queries
mkdir -p ${RESULTDIR}
for s in 1 4 16 48; do
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DBDIR}/kdb/${SIZE} -format kdb -queryfile ./artifacts/queries/kdb.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/kdb_${s}Threads.psv -s ${s}
    QMAP=TRUE numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DBDIR}/kdb/${SIZE} -format kdb -queryfile ./artifacts/queries/kdb_peach.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/kdbPeachQMAP_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DBDIR}/parquet/${SIZE}/hivepartitioned -format parquet -queryfile ./artifacts/queries/parquet_partition.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/parquetHivePartitioned_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DBDIR}/parquet/${SIZE}/rowgroup -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/parquetRowgroup_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DBDIR}/parquet/${SIZE}/rowgroup_minrowgroup_100000 -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/parquetRowgroupMinSize_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DBDIR}/parquet/${SIZE}/rowgroup_maxrowgroupsize250000 -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/parquetRowgroupMaxSize_${s}Threads.psv -s ${s}

    POLARS_MAX_THREADS=$s numactl -N 0 -m 0 python3 pysrc/run_queries.py -engine polars -db ${DBDIR}/parquet/${SIZE}/rowgroup -queryfile ./artifacts/queries/polars.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/polars_${s}Threads.psv
    QARGS="-s ${s}" numactl -N 0 -m 0 python3 pysrc/run_queries.py -engine pykx -db ${DBDIR}/kdb/${SIZE} -queryfile ./artifacts/queries/pykx.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/pykx_${s}Threads.psv
    QARGS="-s ${s}" numactl -N 0 -m 0 python3 pysrc/run_queries.py -engine pykxq -db ${DBDIR}/kdb/${SIZE} -queryfile ./artifacts/queries/kdb.psv -paramdir ./artifacts/parameters/${SIZE} -result ${RESULTDIR}/pykxq_${s}Threads.psv
done

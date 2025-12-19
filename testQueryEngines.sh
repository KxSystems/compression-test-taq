#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

readonly CSVDIR=$1
readonly DSTDIR=$2
readonly DATE=$(get_date $3)

# Step 1: We assume that the CSV files are already downloaded
# Step 2: generate data from CSV files
DATAFORMAT=kdb ./generateDB.sh ${CSVDIR} ${DSTDIR}/kdb${SIZE}/zd0_0_0 ${DATE}
SYMBOLSTOREDAS=PartitionColumn DATAFORMAT=parquet ./generateDB.sh ${CSVDIR} ${DSTDIR}/parquet_partition_nounsigned ${DATE}
SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet ./generateDB.sh ${CSVDIR} ${DSTDIR}/parquet_rowgroup_nounsigned ${DATE}
SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet MINROWGROUPSIZE=100000 ./generateDB.sh ${CSVDIR} ${DSTDIR}/parquet_rowgroup_minrowgroup_100000_nounsigned ${DATE}
SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet MAXROWGROUPSIZE=250000 ./generateDB.sh ${CSVDIR} ${DSTDIR}/parquet_rowgroup_nounsigned_maxrowgroupsize250000 ${DATE}


# Step 3: Generate query parameters
$QEXEC ./artifacts/parameters/genParameters.q -db ${DSTDIR}/kdb${SIZE}/zd0_0_0/ -dst ./artifacts/parameters/${SIZE}

# Step 4: Run queries
for s in 1 4 16 48; do
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DSTDIR}/kdb${SIZE}/zd0_0_0 -format kdb -queryfile ./artifacts/queries/kdb.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/kdbQueries_${s}Threads.psv -s ${s}
    QMAP=TRUE numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DSTDIR}/kdb${SIZE}/zd0_0_0 -format kdb -queryfile ./artifacts/queries/kdb_peach.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/kdbPeachQMAPQueries_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DSTDIR}/parquet_partition_nounsigned -format parquet -queryfile ./artifacts/queries/parquet_partition.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/parquetQueries_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DSTDIR}/parquet_rowgroup_nounsigned -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/parquetRowgroupQueries_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DSTDIR}/parquet_rowgroup_minrowgroup_100000_nounsigned -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/parquetRowgroupMinSizeQueries_${s}Threads.psv -s ${s}
    numactl -N 0 -m 0 $QEXEC ./src/runQueries.q -db ${DSTDIR}/parquet_rowgroup_nounsigned_maxrowgroupsize250000 -format parquet_rowgroup -queryfile ./artifacts/queries/parquet_rowgroup.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/parquetRowgroupMaxSizeQueries_${s}Threads.psv -s ${s}

    POLARS_MAX_THREADS=$s numactl -N 0 -m 0 python3 pysrc/run_queries.py -engine polars -db ${DSTDIR}/parquet_rowgroup_nounsigned -queryfile ./artifacts/queries/polars.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/polars_${s}Threads.psv
    QARGS="-s ${s}" numactl -N 0 -m 0 python3 pysrc/run_queries.py -engine pykx -db ${DSTDIR}/kdb${SIZE}/zd0_0_0 -queryfile ./artifacts/queries/pykx.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/pykx_${s}Threads.psv
    QARGS="-s ${s}" numactl -N 0 -m 0 python3 pysrc/run_queries.py -engine pykxq -db ${DSTDIR}/kdb${SIZE}/zd0_0_0 -queryfile ./artifacts/queries/kdb.psv -paramdir ./artifacts/parameters/${SIZE} -result ./results/pykxq_${s}Threads.psv
done

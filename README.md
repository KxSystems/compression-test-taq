# NYSE TAQ KX Benchmark

## Background

This benchmark uses public
[NYSE TAQ data](https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/)
and representative queries to compare:

* query engines (KDB-X, PyKX, Polars, Pandas, and DuckDB),
* data formats (Parquet vs. kdb+),
* hardware (storage, CPU, memory),
* data layout and settings (compression, attributes, `.Q.MAP`, etc.).

The following engines and formats are currently supported:

| Data format | KDB-X | PyKX | KDB-X SQL | Polars | DuckDB | Pandas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| In memory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| In memory, table dictionary | ✅ | NYI | ❌ | | ❌ | ❌ |
| kdb+ on disk | ✅ | In Progress | ✅ | ❌ | ❌ | ❌ |
| Hive-partitioned Parquet | ✅ | NYI | ❌ | ✅ | NYI | ❌ |
| Parquet, row-group partitioned | ✅ | NYI | ❌ | ✅ | NYI | ❌ |
| Parquet, row-group partitioned (max row group) | ✅ | NYI | ❌ | ✅ | NYI | ❌ |

Parquet data is written using PyArrow.

## Prerequisites

**KDB-X** must be installed. Set the `QHOME` environment variable in
`./config/kdbenv`, then run:

```bash
source ./config/kdbenv
```

The bash and q scripts require:

* `curl`: to download zipped CSV files from the NYSE TAQ server.
* `iostat` (from the `sysstat` package): for disk I/O metrics during query tests.

Python is required to generate Parquet data and run the Polars and KDB-X
Python query engines. Install the required libraries with:

```bash
pip3 install -r ./requirements.txt
```

## Data Size

A single day of NYSE TAQ data is substantial. To reduce test execution time,
you can limit ingestion to a subset of the BBO split CSV files (the source
of the `quote` table).

Set the `SIZE` environment variable in `config/ingestenv` (or pass it
directly to `./generateDB.sh`) to balance execution time against data coverage.

* In all modes except `full`, only a subset of BBO split CSV files is downloaded.
* Only the corresponding trades are converted into the HDB (e.g., only
  symbols starting with `Z`).

Statistics based on data from 2025-01-02:

| `SIZE` | Symbol first letters | HDB size (GB) | Nr of quote symbols | Nr of quotes |
| --- | --- | ---: | ---: | ---: |
| `small` | Z | 1 | 94 | 4 607 158 |
| `medium` | I | 13 | 555 | 180 827 332 |
| `large` | A–H | 52 | 4 849 | 707 738 295 |
| `full` | A–Z | 233 | 11 155 | 2 313 872 956 |

Use `medium` when running the benchmark with KDB-X Community Edition, which
enforces a memory limit.

## Getting the CSV Files

Set the database size in `./config/ingestenv`, then:

```bash
# Fetch the latest available date from the NYSE FTP server
export DATE=$(curl -s https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/| grep -oE 'EQY_US_ALL_TRADE_2[0-9]{7}' | grep -oE '2[0-9]{7}'|head -1)
export NYSEBENCHMARKDIR=/tmp/nysetaqkxbenchmark
source ./config/ingestenv
./getCSVs.sh ${NYSEBENCHMARKDIR}/${SIZE}/csv ${DATE}
```

The `getCSVs.sh` script:

   1. Downloads compressed CSVs using `curl -C` (supports resuming interrupted downloads).
   1. Decompresses the CSV files.
   1. Removes trailing lines from the CSVs.
   1. Adds proper extension (.psv).

## Query Engine In-Memory Benchmark

Query engines read data into memory from Hive-partitioned Parquet or from kdb+ formats. CSV files can be converted to these formats using `./generateDB.sh`:

```bash
$ source ./config/kdbenv
$ DATAFORMAT=kdb ./generateDB.sh ${NYSEBENCHMARKDIR}/${SIZE}/csv ${NYSEBENCHMARKDIR}/${SIZE}/kdb ${DATE}
$ SYMBOLSTOREDAS=ROWGROUP DATAFORMAT=parquet ./generateDB.sh ${NYSEBENCHMARKDIR}/${SIZE}/csv ${NYSEBENCHMARKDIR}/${SIZE}/parquet/rowgroup ${DATE}
```

Once the on-disk data has been generated, you can start the benchmark. To test engines with 0, 4, 16, and 64 secondary threads, run:

```bash
$ export FLUSH=${PWD}/flush/noflush.sh
$ export NUMANODE=0
$ ./testInMemoryEngines.sh --db-dir ${NYSEBENCHMARKDIR}/${SIZE} --param-dir ./artifacts/parameters/${SIZE} --date ${DATE}  --threads "0 4 16 64" --result-dir ./results/dataformats/${SIZE} --stats-dir ./stats/$SIZE
```

## Query Engine On-disk Benchmark

Set environment variables in `config/queryenv`.

```bash
$ source config/queryenv
$ ./testQueryEngines.sh --csv-dir ${NYSEBENCHMARKDIR}/${SIZE}/csv --db-dir ${NYSEBENCHMARKDIR}/${SIZE} \
   --param-dir ./artifacts/parameters/${SIZE} --date ${DATE} \
   --threads "1 4" --result-dir ./results/engines
```

## KDB-X Data Format Benchmark

Set environment variables in `config/queryenv`.

```bash
source config/queryenv
testKDBXDataFormats.sh --csv-dir ${NYSEBENCHMARKDIR}/${SIZE}/csv --db-dir ${NYSEBENCHMARKDIR}/${SIZE} \
   --param-dir ./artifacts/parameters/${SIZE} --date ${DATE} \
   --threads "1 4" --result-dir ./results/engines
```

## kdb+ Compression Benchmark

First, generate uncompressed kdb+ data. Review and configure variables in
`./config/ingestenv`, then:

```bash
source ./config/ingestenv
export DATAFORMAT=kdb
./generateDB.sh ${NYSEBENCHMARKDIR}/${SIZE}/csv ${NYSEBENCHMARKDIR}/${DATAFORMAT} ${DATE}
```

The CSV files are no longer needed after this step. Remove them to free disk
space:

```bash
rm -rf ${NYSEBENCHMARKDIR}/${SIZE}/csv
```

Set environment variables in `config/queryenv`, then run the compression tests:

```bash
export COMPPARAMS="17_0_0 17_2_5 17_3_0 17_4_5 17_5_1"
source config/queryenv
./testCompression.sh ${NYSEBENCHMARKDIR}
```

`COMPPARAMS` is a space-separated list of [compression parameters][kx-comp].
Each parameter is an underscore-separated triple of logical block size,
compression algorithm, and compression level. For example, `17_2_5` specifies
128 KB blocks (2^17), gzip compression (algorithm 2) at level 5.

**Note:** The script flushes the OS page cache before executing the first
query. Since the flush method is storage-specific, you may need to implement
the appropriate command for your system directly in the script.

### Results

The scripts write pipe-separated values (PSV) files to a `results`
subdirectory. The following files are produced for each set of compression
parameters:

* `diskusage.psv`: Storage requirements per column.
* `writetimes.psv`: Execution time of `set` and `sync` for all `trade` columns.
* `query_summary.psv`: Execution time, memory consumption, and disk reads
  for all queries.

Additionally, `columnStatUncompressed.psv` contains basic statistical
information (e.g., [entropy][entropy-wiki]) for all columns.

## Regenerating Query Parameters

```bash
$QEXEC ./artifacts/parameters/genParameters.q -db ${NYSEBENCHMARKDIR}/${SIZE}/kdb -dst ./artifacts/parameters/${SIZE}
```

## Cleanup

Use caution when running cleanup — downloading CSV files or generating the
database can be time-consuming. Run the cleanup script only when the data is
no longer needed.

```bash
rm -rf $NYSEBENCHMARKDIR/csv
./cleanup.sh ${NYSEBENCHMARKDIR} ${DATE}
```

### Hardware Notes

Compression benefits and query engine performance vary significantly with
disk speed and available CPU capacity. For meaningful results, run tests on
storage hardware representative of your production environment.

## Limitations

Only a limited number of days of data are available on the NYSE TAQ site at
any given time. Datasets are updated regularly, with older data replaced by
more recent samples.

[kx-comp]: https://code.kx.com/q/kb/file-compression/#compression-parameters
[entropy-wiki]: https://en.wikipedia.org/wiki/Entropy_(information_theory)

# NYSE TAQ KX Benchmark

## Background

This benchmark uses public [NYSE TAQ data](https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/) and representative queries. The benchmark can be used to compare

* query engines (KDB-X, PyKX Polars, Pandas and DuckDB),
* data formats (parquet vs kdb+),
* hardware (storage, CPU, memory),
* data layout and other settings (compression, attributes, .Q.MAP, etc).

The following engines and formats are currently supported:

| data format | KDB-X | PyKX | KDB-X SQL | Polars | DuckDB | Pandas |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| in memory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅
| in memory, table dictionary | ✅ | NYI | ❌ | In Progress | ❌ | ❌ |
| kdb+ on disk | ✅ | In Progress | ✅ | ❌ | ❌ | ❌ | ❌
| hive partitioned parquet | ✅ | NYI | ❌ | ✅ | NYI | ❌
| parquet rowgroup partitioned | ✅ | NYI | ❌ | ✅ | NYI | ❌
| parquet rowgroup partitioned max row group | ✅ | NYI | ❌ | ✅ | NYI | ❌

The benchmark uses PyArrow to persist data into parquet format.

## Prerequisites

We assume that **KDB-X** is installed. Set the `QHOME` environment variable in `./config/kdbenv` and then run:

```bash
source ./config/kdbenv
```

The bash and q scripts require

* `curl`: To download zipped CSV files from the NYSE TAQ server.
* `iostat` (from the `sysstat` package): For disk I/O metrics during query tests.

You need Python to generate Parquet data and test the Polars and KDB-X Python query engines. Install the required libraries by:

```bash
pip3 install -r ./requirements.txt
```

## Data size

A single day of NYSE TAQ files contain a large amount of data. You can speed up the test if only a part of the BBO split CSV files (source of table `quote`) are considered.

Set the `SIZE` environment variable in `config/ingestenv` (or pass it to `./generateDB.sh`) to balance test execution time and accuracy.

* In all modes except `full`, only a subset of the BBO split CSV files are downloaded.
* Only the corresponding trades will be converted into the HDB (e.g., only symbols starting with 'Z').

Statistics based on data from 2025.01.02:

| `SIZE` | Symbol first letters | HDB size (GB) | Nr of quote Symbols | Nr of quotes |
| --- | --- | ---: | ---: | ---: |
| `small` | Z | 1 | 94 | 4 607 158 |
| `medium` | I | 13 | 555 | 180 827 332 |
| `large` | A-H| 52 | 4849 | 707 738 295 |
| `full` | A-Z | 233 | 11155 | 2 313 872 956 |

Select `medium` SIZE if you run the benchmark with KDB-X community edition (which limits memory usage).

## Getting the CSV files

Set database size in `.config/ingestenv`, then

```bash
# Fetch the latest available date from the NYSE FTP
export DATE=$(curl -s https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/| grep -oE 'EQY_US_ALL_TRADE_2[0-9]{7}' | grep -oE '2[0-9]{7}'|head -1)
export NYSEBENCHMARKDIR=/tmp/nysetaqkxbenchmark
source ./config/ingestenv
./getCSVs.sh ${NYSEBENCHMARKDIR}/csv ${DATE}
```

The script `getCSVs.sh`:

   1. Downloads compressed CSVs using `curl -C` (allows resuming if the connection breaks).
   1. Decompresses the CSV files
   1. Removes the trailing lines of the CSVs.

## Query Engine Benchmark

Set environment variables in `config/queryenv`.

```bash
source config/queryenv
testQueryEngines.sh --csv-dir ${NYSEBENCHMARKDIR}/csv --db-dir ${NYSEBENCHMARKDIR}/${SIZE} \
   --param-dir ./artifacts/parameters/${SIZE} --date ${DATE} \
   --threads "1 4" --result-dir ./results/engines
```

## KDB-X Data Format Benchmark

Set environment variables in `config/queryenv`.

```bash
source config/queryenv
testKDBXDataFormats.sh --csv-dir ${NYSEBENCHMARKDIR}/csv --db-dir ${NYSEBENCHMARKDIR}/${SIZE} \
   --param-dir ./artifacts/parameters/${SIZE} --date ${DATE} \
   --threads "1 4" --result-dir ./results/engines
```

TODO: add more details

## Kdb+ compression benchmark

First, generate uncompressed kdb+ data. Review and set variables in `./config/ingestenv` then

```bash
source ./config/ingestenv
export DATAFORMAT=kdb
./generateDB.sh ${NYSEBENCHMARKDIR}/csv ${NYSEBENCHMARKDIR}/${DATAFORMAT} ${DATE}
```

You no longer need the CSV files, so you might want to delete them to save some space.

```bash
rm -rf ${NYSEBENCHMARKDIR}/csv
```

Set environment variables in `config/queryenv`. Execute compression tests after HDB generation:

```bash
export COMPPARAMS="17_0_0 17_2_5 17_3_0 17_4_5 17_5_1"
source config/queryenv
./testCompression.sh ${NYSEBENCHMARKDIR}
```

`COMPPARAMS` is a list of [compression parameters](https://code.kx.com/q/kb/file-compression/#compression-parameters). A compression parameter is an underscore separated triple of logical block size, compression algorithm and level. For example `17_2_5` means 128KB blocks (17), gzip (2) compression with level 5.

**Note:** The script flushes the page cache before executing the first query. As the flush method is storage-specific, you may need to implement the appropriate command for your system in the script.

### Results

The scripts generate pipe-separated values (PSV) files in a sudirectory `results`. For all compression parameters

* `diskusage.psv`: Storage requirements per column
* `writetimes.psv`: Contains the execution time of `set` and `sync` for all `trade` columns
* `query_summary.psv`: Stores the execution time, memory need and the disk read of all queries

Furthermore, `columnStatUncompressed.psv` stores basic statistical information (e.g. [entropy](https://en.wikipedia.org/wiki/Entropy_(information_theory))) of all columns.

## Regenerating query parameters

```bash
$QEXEC ./artifacts/parameters/genParameters.q -db ${NYSEBENCHMARKDIR}/${SIZE}/kdb -dst ./artifacts/parameters/${SIZE}
```

## Cleanup

Be careful with the cleanup. Downloading CSV files or generating DB might take long. Run the cleanup script if you no longer need the data.

```bash
rm -rf $NYSEBENCHMARKDIR/csv
./cleanup.sh ${NYSEBENCHMARKDIR} ${DATE}
```

### Hardware Notes

Compression benefits and query engine performance vary significantly by disk speed and available CPU capacity. For meaningful results, perform tests on storage hardware that matches your production environment.

## Limitations

Only a few days of data are available on the NYSE TAQ site at any given time. This data is replaced by newer datasets on a regular basis.
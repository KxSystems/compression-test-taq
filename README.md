# NYSE TAQ kdb+ compression tester

## Background

This suite of scripts evaluates kdb+ compression algorithms using public [NYSE TAQ data](https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/). The benchmark measures:

   1. **Compression ratio** (storage efficiency)
   1. **Write performance** (`set` and `sync` operations)
   1. **Query execution times**


It is recommended to read KX [FSI case study](https://code.kx.com/q/kb/compression/fsicasestudy/) for more background.


## Prerequisite

We assume that kdb+ is installed. If the kdb+ home is not `$HOME/q` then set environment variable `QHOME` properly in `config/kdbenv`.

The bash and q script use
   * `wget` to download zipped CSV files from the NYSE TAQ server
   * `iostat` (frome `sysstat` package) for disk I/O metrics
   * Optional: [GNU parallel](https://www.gnu.org/software/parallel/) to unzip NYSE TAQ zipped CSV files in parallel

### Hardware Notes

Compression benefits vary by disk speed and available CPU capacity. For meaningful results, test on storage matching your production environment.

## Data Generation

Only a few days of data is available at the NYSE TAQ site. These data are replaced by newer data on a regular basis. The `generateHDB.sh` script:

   1. Downloads compressed CSVs using `wget -c`. Flag `-c` is used to resume downloading if internet connection breaks.
   1. Extracts files
   1. Generates HDB using modified KX TAQ scripts `src/tq.q`

The compression benefit depends on the disk speed. Build the HDB on a storage that you would like to test. The path of the HDB directory can be passed as the first parameter of `generateHDB.sh`.

```bash
$ export DATE=$(curl -s https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/| grep -oE 'EQY_US_ALL_TRADE_2[0-9]{7}' | grep -oE '2[0-9]{7}'|head -1)
$ source ./config/kdbenv
$ SIZE=full ./generateHDB.sh /tmp/compressiontest $DATE
```

### Data size

A single day of NYSE TAQ files contain large amount of data. You can speed up the test if only a part of the BBO split CSV files (source of table `quote`) are considered. Set the `SIZE` environment variable in `config/env` (or pass it to `./generateHDB.sh`) to balance between test execution time and test accuracy. Except for the `full` mode only a subset of the BBO split CSV files are downloaded and only the corresponding trades will be converted into HDB (e.g. only symbols with Z as the first letter).

Some statistics of various DB sizes with data from 2025.01.02 are below

| `SIZE` | Symbol first letters | HDB size (GB) | Nr of quote Symbols | Nr of quotes | 
| --- | --- | ---: | ---: | ---: |
| `small` | Z | 1 | 94 | 4 607 158 |
| `medium` | I | 13 | 555 | 180 827 332 |
| `large` | A-H| 52 | 4849 | 707 738 295 |
| `full` | A-Z | 233 | 11155 | 2 313 872 956 |

## Running Compression Tests

Execute compression tests after HDB generation:

```bash
$ export COMPPARAMS="17_0_0 17_2_5 17_3_0 17_4_5 17_5_1"
$ ./testCompression.sh /tmp/compressiontest
```

`COMPPARAMS` is a list of [compression parameters](https://code.kx.com/q/kb/file-compression/#compression-parameters). A compression parameter is an underscore separated triple of logical block size, compression algorithm and level. For example `17_2_5` means 128KB blocks (17), gzip (2) compression with level 5.

## Results

The scripts generate pipe-separated values (PSV) files in a sudirectory `results`. For all compression parameters

   * `diskusage.psv`: Storage requirements per column
   * `writetimes.psv`: Contains the execution time of `set` and `sync` for all `trade` columns
   * `query_summary.psv`: Stores the execution time, memory need and the disk read of all queries

Furthermore, `columnStatUncompressed.psv` stores basic statistical information (e.g. [entrophy](https://en.wikipedia.org/wiki/Entropy_(information_theory))) of all columns.

## Cleanup

Be careful with the cleanup. Generating HDB might take long. Run the cleanup script if you no longer need the data.

```bash
$ ./cleanup.sh /tmp/compressiontest $DATE
```

## Details

Persistent settings is also supported by `config/env`:

```bash
$ export DATE=$(curl -s https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/| grep -oE 'EQY_US_ALL_TRADE_2[0-9]{7}' | grep -oE '2[0-9]{7}'|head -1)
$ source ./config/kdbenv
$ source ./config/env
$ ./generateHDB.sh /tmp/compressiontest $DATE
$ ./testCompression.sh /tmp/compressiontest
```


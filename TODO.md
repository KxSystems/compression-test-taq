# Project TODO List

## Next Up

- [ ] `taqToKDB.q`: support compression
- [ ] `taqToKDB.q`: option to avoid loading data into memory, use `.Q.fs`, see https://code.kx.com/q/kb/loading-from-large-files/
- [ ] `parquet.py`: avoid loading data into memory, use a [CSV streaming reader object](https://arrow.apache.org/docs/python/generated/pyarrow.csv.CSVStreamingReader.html#pyarrow.csv.CSVStreamingReader).

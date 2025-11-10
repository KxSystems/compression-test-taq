#!/usr/bin/env python3

"""
Script to parse NYSE TAQ PSV files, transform data using PyArrow,
and persist to a hive-partitioned Parquet dataset.

Environment variables:
    COMPRESSION         Compression algorithm to be used when persisting data, e.g. ZSTD
    COMPRESSION_LEVEL   Level of compression, e.g. 10
"""

import os
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Final, List
from functools import partial

from toolz import pipe

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.dataset as ds
import pyarrow.parquet as pq

# Table master: EQY_US_ALL_REF_MASTER_*.csv
MASTER_SCHEMA: Final[pa.Schema] = pa.schema([
    pa.field('Symbol', pa.string()),
    pa.field('Security_Description', pa.string()),
    pa.field('CUSIP', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Security_Type', pa.dictionary(pa.int32(), pa.string())),
    pa.field('SIP_Symbol', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Old_Symbol', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Test_Symbol_Flag', pa.bool_()),
    pa.field('Listed_Exchange', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Tape', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Unit_Of_Trade', pa.uint16()),
    pa.field('Round_Lot', pa.uint16()),
    pa.field('NYSE_Industry_Code', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Shares_Outstanding', pa.float64()),
    pa.field('Halt_Delay_Reason', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Specialist_Clearing_Agent', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Specialist_Clearing_Number', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Specialist_Post_Number', pa.int16()),
    pa.field('Specialist_Panel', pa.dictionary(pa.int32(), pa.string())),
    pa.field('TradedOnNYSEMKT', pa.bool_()),
    pa.field('TradedOnNASDAQBX', pa.bool_()),
    pa.field('TradedOnNSX', pa.bool_()),
    pa.field('TradedOnFINRA', pa.bool_()),
    pa.field('TradedOnISE', pa.bool_()),
    pa.field('TradedOnEdgeA', pa.bool_()),
    pa.field('TradedOnEdgeX', pa.bool_()),
    pa.field('TradedOnNYSETexas', pa.bool_()),
    pa.field('TradedOnNYSE', pa.bool_()),
    pa.field('TradedOnArca', pa.bool_()),
    pa.field('TradedOnNasdaq', pa.bool_()),
    pa.field('TradedOnCBOE', pa.bool_()),
    pa.field('TradedOnPSX', pa.bool_()),
    pa.field('TradedOnBATSY', pa.bool_()),
    pa.field('TradedOnBATS', pa.bool_()),
    pa.field('TradedOnIEX', pa.bool_()),
    pa.field('Tick_Pilot_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Effective_Date', pa.string()),  # transformed to: pa.date32()
    pa.field('TradedOnLTSE', pa.bool_()),
    pa.field('TradedOnMEMX', pa.bool_()),
    pa.field('TradedOnMIAX', pa.bool_())
])

# Table trade: EQY_US_ALL_TRADE_*.csv
TRADE_SCHEMA: Final[pa.Schema] = pa.schema([
    pa.field('Time', pa.string()), # transformed to: pa.time64('ns')
    pa.field('Exchange', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Symbol', pa.string()),
    pa.field('Sale Condition', pa.string()), # transformed to: pa.dictionary(pa.int32(), pa.string())
    pa.field('Trade Volume', pa.uint32()),
    pa.field('Trade Price', pa.float32()),
    pa.field('Trade Stop Stock Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Trade Correction Indicator', pa.uint16()),
    pa.field('Sequence Number', pa.uint32()),
    pa.field('Trade Id', pa.uint64()),
    pa.field('Source of Trade', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Trade Reporting Facility', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Participant Timestamp', pa.string()), # transformed to: pa.time64('ns')
    pa.field('Trade Reporting Facility TRF Timestamp', pa.string()), # transformed to: pa.time64('ns')
    pa.field('Trade Through Exempt Indicator', pa.bool_())
])

# Table quote: splits_us_all_bbo_*[0-9]_*.csv
QUOTE_SCHEMA: Final[pa.Schema] = pa.schema([
    pa.field('Time', pa.string()),  # transformed to pa.time64('ns')
    pa.field('Exchange', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Symbol', pa.string()),
    pa.field('Bid_Price', pa.float32()),
    pa.field('Bid_Size', pa.uint32()),
    pa.field('Offer_Price', pa.float32()),
    pa.field('Offer_Size', pa.uint32()),
    pa.field('Quote_Condition', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Sequence_Number', pa.uint32()),
    pa.field('National_BBO_Ind', pa.dictionary(pa.int32(), pa.string())),
    pa.field('FINRA_BBO_Indicator', pa.string()), # transformed to pa.dictionary(pa.int32(), pa.string())
    pa.field('FINRA_ADF_MPID_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Quote_Cancel_Correction', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Source_Of_Quote', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Retail_Interest_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Short_Sale_Restriction_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('LULD_BBO_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('SIP_Generated_Message_Identifier', pa.dictionary(pa.int32(), pa.string())),
    pa.field('National_BBO_LULD_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Participant_Timestamp', pa.string()), # transformed to pa.time64('ns')
    pa.field('FINRA_ADF_Timestamp', pa.string()),   # transformed to pa.time64('ns')
    pa.field('FINRA_ADF_Market_Participant_Quote_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Security_Status_Indicator', pa.dictionary(pa.int32(), pa.string()))
])

PARSE_OPTIONS = csv.ParseOptions(delimiter='|')

IDENTITY = lambda x: x

# --- Helper Functions ---

def get_convert_options(schema: pa.Schema) -> pa.csv.ConvertOptions:
    """Creates CSV convert options for a given schema.

    Sets up column types, boolean true/false values, and date parsers
    based on the input schema.

    Args:
        schema: The PyArrow schema to use for column type conversion.

    Returns:
        A PyArrow `csv.ConvertOptions` object.
    """
    return csv.ConvertOptions(
        column_types=schema,
        include_columns=schema.names,

        true_values=['Y', '1'],
        false_values=['N', '0'],

        timestamp_parsers=["%Y%m%d"]
    )

# --- Table convert Functions ---

def letter_filter(start_char: str, end_char: str, table: pa.Table) -> pa.Table:
    """Filters a table based on the first letter of the 'Symbol' column.

    Includes rows where the first character of the trimmed 'Symbol'
    is within the specified inclusive range.

    Args:
        start_char: The starting character of the range (e.g., 'A').
        end_char: The ending character of the range (e.g., 'K').
        table: The input PyArrow table to filter.

    Returns:
        The filtered PyArrow table.
    """
    logging.info("    Filtering based on the first letter of the Symbol values")
    symbol_col = pc.utf8_trim_whitespace(table['Symbol'])
    first_chars = pc.utf8_slice_codeunits(symbol_col, 0, 1)
    filter_expression = pc.and_(
        pc.greater_equal(first_chars, start_char),
        pc.less_equal(first_chars, end_char)
    )
    return table.filter(filter_expression)

def symbol_conv(table: pa.Table) -> pa.Table:
    """Cleans the 'Symbol' column by replacing whitespace with dots.

    Args:
        table: The input PyArrow table.

    Returns:
        The table with the modified 'Symbol' column.
    """
    logging.info("    Converting the Symbol column")
    symbol_col = pc.replace_substring_regex(
        table['Symbol'],
        pattern=r'\s+',
        replacement='.')
    return table.set_column(
        table.schema.get_field_index('Symbol'), 'Symbol', symbol_col)

def trim_dict_encode(trim_cols: List[str], table: pa.Table) -> pa.Table:
    """Trims whitespace and dictionary-encodes specified string columns.

    Args:
        trim_cols: A list of column names to process.
        table: The input PyArrow table.

    Returns:
        The table with the modified columns.
    """
    logging.info("    Trimming and dictionary encoding some columns")
    for col_name in trim_cols:
        trimmed_col = pc.utf8_trim_whitespace(table[col_name])
        casted_column = trimmed_col.cast(pa.dictionary(pa.int32(), pa.string()))
        table = table.set_column(table.schema.get_field_index(col_name), col_name, casted_column)
    return table

def convert_time_string_array_to_time64(time_strings: pa.Array) -> pa.Array:
    """Converts a string array of 'HHMMSSNNNNNNNNN' to pa.time64('ns').

    This function is designed for high performance using PyArrow compute
    functions. It handles empty strings ('') as null values.

    Note:
        Assumes a strict 15-character format (or empty string).
        Malformed, non-empty strings may cause errors.

    Args:
        time_strings: A PyArrow string array with time values.

    Returns:
        A PyArrow array of type `pa.time64('ns')`.
    """

    null_idx = pc.equal(time_strings, '')
    # Replace nulls with a valid-format string to avoid slice errors
    time_strings_safe = pc.if_else(
        null_idx,
        pa.scalar('000000000000000'),
        time_strings
    )

    # Extract components using string slicing
    hours = pc.utf8_slice_codeunits(time_strings_safe, 0, 2)
    minutes = pc.utf8_slice_codeunits(time_strings_safe, 2, 4)
    seconds = pc.utf8_slice_codeunits(time_strings_safe, 4, 6)
    nanoseconds = pc.utf8_slice_codeunits(time_strings_safe, 6, 15)

    # Convert to integers
    hours_int = pc.cast(hours, pa.int64())
    minutes_int = pc.cast(minutes, pa.int64())
    seconds_int = pc.cast(seconds, pa.int64())
    nanoseconds_int = pc.cast(nanoseconds, pa.int64())

    # Calculate total nanoseconds from midnight
    total_ns = pc.add(
        pc.multiply(
            pc.add(
                pc.add(
                    pc.multiply(hours_int, 3600),
                    pc.multiply(minutes_int, 60)
                ),
            seconds_int
            ),
            1_000_000_000
        ),
        nanoseconds_int
    )

    # Re-apply nulls and cast to the final time64[ns] type
    return pc.if_else(null_idx, None, pc.cast(total_ns, pa.time64('ns')))

def convert_time_strings_to_time64(time_cols: List[str], table: pa.Table) -> pa.Table:
    """Applies `time64[ns]` conversion to multiple time columns in a table.

    Args:
        time_cols: List of column names to convert.
        table: The input PyArrow table.

    Returns:
        The table with converted time columns.
    """
    logging.info("    Converting some string columns to time64 columns")
    for col_name in time_cols:
        time_col = convert_time_string_array_to_time64(table[col_name])
        table = table.set_column(table.schema.get_field_index(col_name), col_name, time_col)
    return table

def convert_date_strings_to_date32(date_cols: List[str], table: pa.Table) -> pa.Table:
    """Converts 'YYYYMMDD' string columns to `pa.date32`.

    Handles empty strings as nulls.

    Args:
        date_cols: List of column names to convert.
        table: The input PyArrow table.

    Returns:
        The table with converted date columns.
    """
    logging.info("    Converting some string columns to date32 columns")
    for col_name in date_cols:
        date_col = pc.strptime(pc.if_else(
                pc.equal(pc.utf8_length(table[col_name]), 0), None, table[col_name]
                ),
                format="%Y%m%d",
                unit="s"
                )
        table = table.set_column(table.schema.get_field_index(col_name), col_name, date_col)
    return table

def add_date_column(date: datetime, table: pa.Table) -> pa.Table:
    """Adds a 'date' column to the table based on the filename.

    This 'date' column is intended for Hive partitioning.

    Args:
        date: The date values of the column to add.
        table: The input PyArrow table.

    Returns:
        The table with the new 'date' column. If no date is found
        in the filename, the column will be all nulls.
    """
    logging.info("    Adding date column")
    date_array = pa.array([date.date()] * len(table), type=pa.date32())
    return table.append_column('date', date_array)

def standardize_column_names(table: pa.Table) -> pa.Table:
    """Standardizes column names by removing spaces and underscores.

    Example: 'Sale Condition' becomes 'SaleCondition'.

    Args:
        table: The input PyArrow table.

    Returns:
        The table with renamed columns.
    """
    logging.info("    Standardizing column names")
    new_names = [name.replace(" ", "").replace("_", "") for name in table.column_names]
    return table.rename_columns(new_names)

def test_symbol_filter(test_symbols: pa.Array, table: pa.Table) -> pa.Table:
    """Filtering out test symbol entries.

    Args:
        test_symbols: an array of the test symbols
        table: The input PyArrow table.

    Returns:
        The table without test symbols.
    """
    logging.info("    Filtering out test symbol entries")
    return table.filter(pc.invert(pc.is_in(table['Symbol'], test_symbols)))

# --- Main Processing ---
def get_write_options(sort_idx: int) -> ds.FileWriteOptions:
    """Get file write options (e.g. compression algorithm) based on environment variables.
    """
    compression = os.getenv('COMPRESSION')
    write_kwargs = {}
    if compression:
        logging.info(f"Setting parquet compression to {compression}")
        write_kwargs['compression'] = compression
    else:
        write_kwargs['compression'] = None

    compression_level = os.getenv('COMPRESSION_LEVEL')
    if compression_level:
        logging.info(f"Setting parquet compression level to {compression_level}")
        write_kwargs['compression_level'] = int(compression_level)

    write_kwargs['sorting_columns'] = [pq.SortingColumn(sort_idx)] # sorted by Time, a bit ugly hardcoding!

    return ds.ParquetFileFormat().make_write_options(**write_kwargs)

def parse_and_convert(file_path: Path, schema: pa.Schema, conv: List) -> pa.Table:
    """Parses a PSV file into a Pyarrow table and applies a list of transformation function on the table.

    Args:
        file_path: Path to the input PSV file.
        schema: The PyArrow schema for reading the file.
        conv: A list of transformation functions to pipe the table through.

    Returns:
        The parsed and transformed table.
    """
    convert_options = get_convert_options(schema)

    table = csv.read_csv(
        file_path,
        parse_options=PARSE_OPTIONS,
        convert_options=convert_options,
        # encoding should be ascii or utf-8 but Security_Description
        # may contain invalid characters
        read_options=csv.ReadOptions(encoding='latin1')
    )
    logging.info("  Renaming and converting")
    return pipe(table, *conv)

def persist(table: pa.Table, table_output_path: Path, partition_schema: pa.Schema, parquet_options: ds.FileWriteOptions) -> None:
    """Persists a Pyarrow table to a Parquet dataset.

    Args:
        table: The table to persist
        table_output_path: The root directory for the output Parquet dataset.
        partition_schema: The schema to use for Hive partitioning.
    """
    if len(table) == 0:
        logging.info("  No rows after converting. Nothing to save.")
    else:
        logging.info(f"  Saving {len(table)} rows")
        ds.write_dataset(
            table,
            base_dir=table_output_path,
            format='parquet',
            partitioning=ds.partitioning(partition_schema, flavor='hive'),
            max_partitions=15000,
            existing_data_behavior='overwrite_or_ignore',
            file_options=parquet_options,
            preserve_order=True # Assumes original data is sorted by Time
        )
        logging.info(f"  Successfully wrote data to {table_output_path}")

def process(file_path: Path, schema: pa.Schema, table_output_path: Path,
            conv: List, partition_schema: pa.Schema, parquet_options: ds.FileWriteOptions) -> None:
    """Reads, transforms, and persists a single PSV file to a Parquet dataset.

    Args:
        file_path: Path to the input PSV file.
        schema: The PyArrow schema for reading the file.
        table_output_path: The root directory for the output Parquet dataset.
        conv: A list of transformation functions to pipe the table through.
        partition_schema: The schema to use for Hive partitioning.
    """
    try:
        table = parse_and_convert(file_path, schema, conv)
        persist(table, table_output_path, partition_schema, parquet_options)
    except Exception as e:
        logging.error(
            "Error processing file %s: %s", file_path, e, exc_info=True
        )

def main(date: datetime, src: Path, dst: Path, letters: str, includetestsymbols: bool) -> None:
    """Main entry point to find, process, and persist all data files.

    Args:
        src: Directory containing the input PSV files.
        dst: Directory to save the output Parquet files.
        letters: Letter range (e.g., "A-K") to filter symbols.

    Raises:
        SystemExit: If the source directory is invalid or the 'letters'
                    argument is malformed.
    """
    start_time = datetime.now()
    if not src.is_dir():
        logging.error("Error: Data directory '%s' not found or is not a directory.", src)
        sys.exit(1)

    dst.mkdir(parents=True, exist_ok=True)

    if letters == "A-Z":
        first_letter_filter = IDENTITY
    else:
        try:
            start_char, end_char = letters.split('-')
            if len(start_char) != 1 or len(end_char) != 1:
                 raise ValueError("Range must consist of single characters.")
            first_letter_filter = partial(letter_filter, start_char, end_char)
        except ValueError:
            logging.error(
                "Invalid letter parameter: '%s'. Must be in form START-END "
                "(e.g., A-K or L-Z).",
                letters
            )
            sys.exit(1)

    datestr = date.strftime('%Y%m%d')

    # Process master files
    logging.info("Processing master table")
    master_file = f"{src}/EQY_US_ALL_REF_MASTER_{datestr}.psv"

    logging.info(f"  Parsing file {master_file}")
    # no compression for the small master table
    master = parse_and_convert(master_file, MASTER_SCHEMA, [first_letter_filter])
    if includetestsymbols:
        master_extra_conv = extra_conv = IDENTITY
    else:
        test_symbols = master['Symbol'].filter(master['Test_Symbol_Flag'])
        master_extra_conv = lambda t: t.filter(pc.invert(t['Test_Symbol_Flag']))
        extra_conv = partial(test_symbol_filter, test_symbols)

    master_conv= [master_extra_conv, symbol_conv,
                  partial(convert_date_strings_to_date32, ['Effective_Date']),
                  partial(add_date_column, date), standardize_column_names]
    master= pipe(master, *master_conv)
    parquet_options_master = ds.ParquetFileFormat().make_write_options(compression='none')
    persist(master, dst / 'master', pa.schema([('date', pa.date32())]), parquet_options_master)
    # Process quote files
    logging.info("Processing quote tables")
    quote_files = list(src.glob(f"SPLITS_US_ALL_BBO_[{letters}]_{datestr}.psv")) # first letter filter happens here
    quote_conv = [extra_conv, symbol_conv,
            partial(trim_dict_encode, ['FINRA_BBO_Indicator']),
            partial(convert_time_strings_to_time64, ['Time', 'Participant_Timestamp', 'FINRA_ADF_Timestamp']),
            partial(add_date_column, date), standardize_column_names]
    parquet_options_quote = get_write_options(QUOTE_SCHEMA.get_field_index('TIME'))
    for file_path in quote_files:
        logging.info(f"  Parsing file {file_path}", )
        process(file_path, QUOTE_SCHEMA, dst / 'quote', quote_conv,
            pa.schema([('date', pa.date32()), ('Symbol', pa.string())]), parquet_options_quote)

    # Process trade files
    logging.info("Processing trade tables")
    trade_file = f"{src}/EQY_US_ALL_TRADE_{datestr}.psv"
    logging.info(f"  Parsing file {trade_file}")
    trade_conv = [first_letter_filter, extra_conv, symbol_conv,
        partial(trim_dict_encode, ['Sale Condition']),
        partial(convert_time_strings_to_time64, ['Time', 'Participant Timestamp', 'Trade Reporting Facility TRF Timestamp']),
        partial(add_date_column, date), standardize_column_names]
    parquet_options_trade = get_write_options(TRADE_SCHEMA.get_field_index('TIME'))
    process(trade_file, TRADE_SCHEMA, dst / 'trade', trade_conv,
        pa.schema([('date', pa.date32()), ('Symbol', pa.string())]), parquet_options_trade)

    elapsed = datetime.now() - start_time
    logging.info(f"\nAll processing completed in {elapsed}")

def parse_yyyymmdd(date_str: str):
    """
    Converts a YYYYMMDD string to a datetime.datetime object.

    Args:
        date_str: The date string in 'YYYYMMDD' format (e.g., '20250701').

    Returns:
        A datetime.datetime object.
    """
    try:
        # '%Y' for four-digit year, '%m' for month, '%d' for day
        date_object = datetime.strptime(date_str, '%Y%m%d')
        return date_object
    except ValueError:
        # If the string doesn't match the format, raise a ValueError
        # to let argparse handle the error gracefully.
        raise argparse.ArgumentTypeError(
            f"Invalid date format: '{date_str}'. Expected YYYYMMDD (e.g., 20250701)."
        )

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Parses NYSE TAQ PSV files and persists to a partitioned Parquet dataset.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-date', type=parse_yyyymmdd, required=True,
         help="Date to process in YYYYMMDD format, e.g. 20250701."
    )
    parser.add_argument(
        '-src', type=Path, required=True,
        help="Directory containing the input PSV files."
    )
    parser.add_argument(
        '-dst', type=Path, default='parquetDB',
        help="Directory to save the output Parquet files. Defaults to 'parquetDB'."
    )

    parser.add_argument(
        '-letters', type=str, default='A-Z',
        help="Symbol range to process, e.g., 'A-K'. Defaults to 'A-Z'."
    )

    parser.add_argument(
        '-includetestsymbols', action='store_true',
        help="True if test symbols should be skipped. Defaults to False."
    )
    args = parser.parse_args()

# --- Logging Setup ---
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    main(args.date, args.src, args.dst, args.letters.upper(), args.includetestsymbols)

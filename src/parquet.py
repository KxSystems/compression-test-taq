#!/usr/bin/env python3

"""
Script to parse NYSE TAQ PSV files, transform data using PyArrow,
and persist to a partitioned Parquet dataset.
"""

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Final, List, Optional

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.dataset as ds

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
    pa.field('Unit_Of_Trade', pa.int16()),
    pa.field('Round_Lot', pa.int16()),
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
    pa.field('Trade Volume', pa.int32()),
    pa.field('Trade Price', pa.float32()),
    pa.field('Trade Stop Stock Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Trade Correction Indicator', pa.int16()),
    pa.field('Sequence Number', pa.int32()),
    pa.field('Trade Id', pa.string()),
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
    pa.field('Bid_Price', pa.float64()),
    pa.field('Bid_Size', pa.int32()),
    pa.field('Offer_Price', pa.float64()),
    pa.field('Offer_Size', pa.int32()),
    pa.field('Quote_Condition', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Sequence_Number', pa.int32()),
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

# Schema for Hive-style partitioning
PARTITION_SCHEMA: Final[pa.Schema] = pa.schema([
        ('date', pa.date32()),
        ('Symbol', pa.string())
        ])

# --- Helper Functions ---

def get_date_from_filename(filepath: Path) -> Optional[str]:
    """Extracts an 8-digit date from a filename."""
    match = re.search(r'(\d{8})', filepath.name)
    if match:
        return match.group(1)
    return None

def letter_conv(table: pa.Table, start_char: str, end_char: str) -> pa.Table:
    """
    Filters a PyArrow Table to include only rows where the 'Symbol'
    starts with a character within the specified range.
    """
    symbol_col = pc.utf8_trim_whitespace(table['Symbol'])
    first_chars = pc.utf8_slice_codeunits(symbol_col, 0, 1)
    filter_expression = pc.and_(
        pc.greater_equal(first_chars, start_char),
        pc.less_equal(first_chars, end_char)
    )
    return table.filter(filter_expression)

def symbol_conv(table: pa.Table) -> pa.Table:
    """
    Cleans the 'Symbol' column by replacing one or more
    whitespace characters with a single dot.
    """
    symbol_col = pc.replace_substring_regex(
        table['Symbol'],
        pattern=r'\s+',
        replacement='.')
    return table.set_column(
        table.schema.get_field_index('Symbol'), 'Symbol', symbol_col)

def convert_time_strings_to_time64(time_strings: pa.Array) -> pa.Array:
    """
    Converts a PyArrow Array of time strings (format HHMMSSNNNNNNNNN)
    to a pa.time64('ns') array.
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

# --- Main Processing ---

def process_and_persist(file_paths: List[Path],schema: pa.Schema,
    output_path: Path, table_name: str, start_char: str, end_char: str,
    trim_cols: List[str], time_cols: List[str], date_cols: List[str],
    partition_schema: Final[pa.Schema]
) -> None:
    """
    Reads, processes, and persists a list of PSV files to a
    partitioned Parquet dataset.

    Args:
        file_paths: List of file paths to process.
        schema: The PyArrow schema to use for reading.
        output_path: The root directory for the Parquet dataset.
        table_name: The name of the table (e.g., 'quote', 'trade').
        start_char: Start character for symbol filtering.
        end_char: End character for symbol filtering.
        trim_cols: List of string columns to trim and cast to dictionary.
        time_cols: List of string columns to convert to time64[ns].
        date_cols: List of string columns to convert to date32.
        partition_schema: partition schema
    """
    logging.info("Processing table %s", table_name)
    if not file_paths:
        logging.info("No input files found for %s. Skipping.", table_name)
        return

    parse_options = csv.ParseOptions(delimiter='|')
    convert_options = csv.ConvertOptions(
        column_types=schema,
        include_columns=schema.names,

        true_values=['Y', '1'],
        false_values=['N', '0'],

        timestamp_parsers=["%Y%m%d"]
    )

    parquet_options = ds.ParquetFileFormat().make_write_options(
        compression='none'
    )

    table_output_path = output_path / table_name

    for file_path in file_paths:
        logging.info("  Parsing file %s", file_path.name)

        try:
            # Read the PSV directly into a PyArrow Table
            table = csv.read_csv(
                file_path,
                parse_options=parse_options,
                convert_options=convert_options,
                # encoding should be ascii or utf-8 but Security_Description
                # may contain invalid characters
                read_options=csv.ReadOptions(encoding='latin1')
            )
            logging.info("  Renaming and converting")
            table = letter_conv(table, start_char, end_char)

            if len(table) == 0:
                logging.info("  No rows after filtering for file: %s", file_path.name)
                continue

            table = symbol_conv(table)

            # Trim and dictionary-encode specified columns
            for col_name in trim_cols:
                trimmed_col = pc.utf8_trim_whitespace(table[col_name])
                casted_column = trimmed_col.cast(pa.dictionary(pa.int32(), pa.string()))
                table = table.set_column(
                    table.schema.get_field_index(col_name), col_name, casted_column
                    )

            # Convert time string columns
            for col_name in time_cols:
                time_col = convert_time_strings_to_time64(table[col_name])
                table = table.set_column(
                    table.schema.get_field_index(col_name), col_name, time_col
                    )

            for col_name in date_cols:
                date_col = pc.strptime(pc.if_else(
                    pc.equal(pc.utf8_length(table[col_name]), 0), None,table[col_name]
                    ),
                    format="%Y%m%d",
                    unit="s"
                    )
                table = table.set_column(
                    table.schema.get_field_index(col_name), col_name, date_col
                    )

            # Add 'date' column for partitioning
            date_str = get_date_from_filename(file_path)
            if not date_str:
                logging.warning(
                    "    Could not extract date from %s. Skipping file.",
                    file_path.name
                )
                continue

            date_obj = datetime.strptime(date_str, '%Y%m%d').date()
            date_array = pa.array([date_obj] * len(table), type=pa.date32())
            table = table.append_column('date', date_array)

            # Standardize column names (remove spaces and underscores)
            new_names = [name.replace(" ", "").replace("_", "") for name in table.column_names]
            table = table.rename_columns(new_names)

            logging.info("  Writing %d rows", len(table))
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
            logging.info("  Successfully wrote data to %s", table_output_path)

        except Exception as e:
            logging.error(
                "Error processing file %s: %s", file_path, e, exc_info=True
            )
            continue

def main(src: Path, dst: Path, letters: str) -> None:
    """
    Main function to find, process, and persist data files.

    Args:
        src: Directory containing the input PSV files.
        dst: Directory to save the output Parquet files.
        letters: Letter range (e.g., "A-K") to filter symbols.
    """
    if not src.is_dir():
        logging.error("Error: Data directory '%s' not found or is not a directory.", src)
        sys.exit(1)

    dst.mkdir(parents=True, exist_ok=True)

    try:
        start_char, end_char = letters.split('-')
        if len(start_char) != 1 or len(end_char) != 1:
             raise ValueError("Range must consist of single characters.")
    except ValueError:
        logging.error(
            "Invalid letter parameter: '%s'. Must be in form START-END "
            "(e.g., A-K or L-Z).",
            letters
        )
        sys.exit(1)

    # Process master files
    master_files = list(src.glob('EQY_US_ALL_REF_MASTER_*.psv'))
    process_and_persist(master_files, MASTER_SCHEMA, dst, 'master', start_char, end_char,
                        [], [], ['Effective_Date'], pa.schema([('date', pa.date32())]))

    # Process quote files
    quote_files = list(src.glob(f"SPLITS_US_ALL_BBO_[{letters}]_*.psv"))
    process_and_persist(quote_files, QUOTE_SCHEMA, dst, 'quote', start_char, end_char,
                        ['FINRA_BBO_Indicator'], ['Time', 'Participant_Timestamp', 'FINRA_ADF_Timestamp'], [],
                        pa.schema([('date', pa.date32()), ('Symbol', pa.string())]))

    # Process trade files
    trade_files = list(src.glob('EQY_US_ALL_TRADE_*.psv'))
    process_and_persist(trade_files, TRADE_SCHEMA, dst, 'trade', start_char, end_char,
                        ['Sale Condition'], ['Time', 'Participant Timestamp', 'Trade Reporting Facility TRF Timestamp'], [],
                        pa.schema([('date', pa.date32()), ('Symbol', pa.string())]))

    logging.info("\nAll processing complete.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Parses NYSE TAQ PSV files and persists to a partitioned Parquet dataset.",
        formatter_class=argparse.RawTextHelpFormatter
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
    args = parser.parse_args()

# --- Logging Setup ---
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    main(args.src, args.dst, args.letters)

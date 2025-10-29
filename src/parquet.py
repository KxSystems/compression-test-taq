import pyarrow as pa
import pyarrow.csv as csv
import pyarrow.compute as pc
import pyarrow.dataset as ds
import os
import glob
import re
import argparse
from datetime import datetime

# Table trade: EQY_US_ALL_TRADE_*.csv
TRADE_SCHEMA = pa.schema([
    pa.field('Time', pa.string()), # pa.time64('ns')
    pa.field('Exchange', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Symbol', pa.string()),
    pa.field('Sale Condition', pa.string()), # pa.dictionary(pa.int32(), pa.string())
    pa.field('Trade Volume', pa.int32()),
    pa.field('Trade Price', pa.float32()),
    pa.field('Trade Stop Stock Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Trade Correction Indicator', pa.int16()),
    pa.field('Sequence Number', pa.int32()),
    pa.field('Trade Id', pa.string()),
    pa.field('Source of Trade', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Trade Reporting Facility', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Participant Timestamp', pa.string()), # pa.time64('ns')
    pa.field('Trade Reporting Facility TRF Timestamp', pa.string()), # pa.time64('ns')
    pa.field('Trade Through Exempt Indicator', pa.bool_())
])

# Table quote: splits_us_all_bbo_*[0-9]_*.csv
QUOTE_SCHEMA = pa.schema([
    pa.field('Time', pa.string()),  # pa.time64('ns')
    pa.field('Exchange', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Symbol', pa.string()),
    pa.field('Bid_Price', pa.float64()),
    pa.field('Bid_Size', pa.int32()),
    pa.field('Offer_Price', pa.float64()),
    pa.field('Offer_Size', pa.int32()),
    pa.field('Quote_Condition', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Sequence_Number', pa.int32()),
    pa.field('National_BBO_Ind', pa.dictionary(pa.int32(), pa.string())),
    pa.field('FINRA_BBO_Indicator', pa.string()), # pa.dictionary(pa.int32(), pa.string())
    pa.field('FINRA_ADF_MPID_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Quote_Cancel_Correction', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Source_Of_Quote', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Retail_Interest_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Short_Sale_Restriction_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('LULD_BBO_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('SIP_Generated_Message_Identifier', pa.dictionary(pa.int32(), pa.string())),
    pa.field('National_BBO_LULD_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Participant_Timestamp', pa.string()), # pa.time64('ns')
    pa.field('FINRA_ADF_Timestamp', pa.string()),   # pa.time64('ns')
    pa.field('FINRA_ADF_Market_Participant_Quote_Indicator', pa.dictionary(pa.int32(), pa.string())),
    pa.field('Security_Status_Indicator', pa.dictionary(pa.int32(), pa.string()))
])

PARTITION_SCHEMA = pa.schema([
        ('date', pa.date32()),
        ('Symbol', pa.string())
        ])

def get_date_from_filename(filepath):
    """Extracts an 8-digit date from a filename."""
    match = re.search(r'(\d{8})', os.path.basename(filepath))
    if match:
        return match.group(1)
    return None

def letter_conv(table, start_char, end_char):
    """
    Filter
    """
    symbol_col = pc.utf8_trim_whitespace(table['Symbol'])
    first_chars = pc.utf8_slice_codeunits(symbol_col, 0, 1)
    filter_expression = pc.and_(
        pc.greater_equal(first_chars, start_char),
        pc.less_equal(first_chars, end_char)
    )
    return table.filter(filter_expression)

def symbol_conv(table):
    """
    Clean Symbol column: replace whitespaces with a dots
    """
    symbol_col = pc.replace_substring_regex(table['Symbol'], pattern=r'\s+', replacement='.')
    return table.set_column(table.schema.get_field_index('Symbol'), 'Symbol', symbol_col)


def convert_time_strings_to_time64(time_strings):
    """
    Convert a list of time strings of format HHMMSSNNNNNNNNN
    (like '093709677326165') to pa.time64('ns') array
    """

    null_idx= pc.equal(time_strings, '')
    time_strings_new = pc.if_else(
        null_idx,
        pa.scalar('000000000000000'),
        time_strings
    )

    # Extract components using string slicing
    hours = pc.utf8_slice_codeunits(time_strings_new, 0, 2)
    minutes = pc.utf8_slice_codeunits(time_strings_new, 2, 4)
    seconds = pc.utf8_slice_codeunits(time_strings_new, 4, 6)
    nanoseconds = pc.utf8_slice_codeunits(time_strings_new, 6, 15)

    # Convert to integers
    hours_int = pc.cast(hours, pa.int64())
    minutes_int = pc.cast(minutes, pa.int64())
    seconds_int = pc.cast(seconds, pa.int64())
    nanoseconds_int = pc.cast(nanoseconds, pa.int64())

    # Calculate total nanoseconds
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

    return pc.if_else(null_idx, None, pc.cast(total_ns, pa.time64('ns')))

def process_and_persist(file_paths, schema, output_path, table_name, start_char, end_char, trimcols, timecols):
    """
    Parses a list of CSV files using PyArrow, processes them, and persists
    them to a partitioned Parquet dataset.
    """
    print(f"--- Starting processing for table: {table_name} ---")
    if not file_paths:
        print(f"No input files found for {table_name}. Skipping.")
        return

    for file_path in file_paths:
        print(f"  Reading file: {os.path.basename(file_path)}")

        try:
            parse_options = csv.ParseOptions(delimiter='|')
            convert_options = csv.ConvertOptions(
                column_types=schema,
                include_columns=schema.names
            )

            # Read the CSV directly into a PyArrow Table
            table = csv.read_csv(
                file_path,
                parse_options=parse_options,
                convert_options=convert_options
            )

            table=letter_conv(table, start_char, end_char)

            if len(table) > 0: # no need to pollute data directory
                table = symbol_conv(table)

                for trimcol in trimcols:
                    newcol = pc.utf8_trim_whitespace(table[trimcol])
                    casted_column = newcol.cast(pa.dictionary(pa.int32(), pa.string()))
                    table = table.set_column(table.schema.get_field_index(trimcol), trimcol, casted_column)

                for timecol in timecols:
                    newcol = convert_time_strings_to_time64(table[timecol])
                    table = table.set_column(table.schema.get_field_index(timecol), timecol, newcol)

                # Add date column for partitioning
                date_str = get_date_from_filename(file_path)
                if not date_str:
                    print(f"    Warning: Could not extract date from {file_path}. Skipping file.")
                    continue
                date_obj = datetime.strptime(date_str, '%Y%m%d').date()
                date_array = pa.array([date_obj] * len(table), type=pa.date32())
                table = table.append_column('date', date_array)

                # remove whitespaces and underscores from column names
                table = table.rename_columns([name.replace(" ", "").replace("_", "") for name in table.column_names])

                table_output_path = os.path.join(output_path, table_name)

                print(f"  Writing partitioned Parquet dataset to: {table_output_path}")
                ds.write_dataset(
                    table,
                    base_dir=table_output_path,
                    format='parquet',
                    partitioning=ds.partitioning(PARTITION_SCHEMA, flavor='hive'),
                    max_partitions=15000,
                    existing_data_behavior='overwrite_or_ignore',
                    file_options=ds.ParquetFileFormat().make_write_options(compression='none'),
                    preserve_order=True # original data is sorted by Time
                )
                print(f"  Successfully wrote {table_name} data. Nr of rows: {len(table)}")

        except Exception as e:
            print(f"    Error processing file {file_path}: {e}")
            continue

def main(data_dir, output_dir, first_letter_interval):
    """Main function to find and process data files."""
    if not os.path.exists(data_dir):
        print(f"Error: Data directory '{data_dir}' not found.")
        return

    os.makedirs(output_dir, exist_ok=True)
    try:
        start_char, end_char = first_letter_interval.split('-')
    except ValueError:
        raise ValueError(f"Invalid letter parameter. Must be in form START-END, for example A-K, got '{first_letter_interval}'")

    # Process quote files
    quote_files = glob.glob(os.path.join(data_dir, f"SPLITS_US_ALL_BBO_[{first_letter_interval}]_*.psv"))
    process_and_persist(quote_files, QUOTE_SCHEMA, output_dir, 'quote', start_char, end_char, ['FINRA_BBO_Indicator'], ['Time', 'Participant_Timestamp', 'FINRA_ADF_Timestamp'])

    # Process trade files
    trade_files = glob.glob(os.path.join(data_dir, 'EQY_US_ALL_TRADE_*.psv'))
    process_and_persist(trade_files, TRADE_SCHEMA, output_dir, 'trade', start_char, end_char, ['Sale Condition'], ['Time', 'Participant Timestamp', 'Trade Reporting Facility TRF Timestamp'])

    print("\nAll processing complete.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Parses NYSE TAQ PSV files and persists to a partitioned Parquet dataset.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-src', type=str, required=True,
        help="Directory containing the input PSV files."
    )
    parser.add_argument(
        '-dst', type=str, default='parquetDB',
        help="Directory to save the output Parquet files. Defaults to 'parquetDB'."
    )

    parser.add_argument(
        '-letters', type=str, default='A-Z',
        help="Letters allowed as first letter of the Symbol column. Defaults to 'A-Z', which is allow all."
    )
    args = parser.parse_args()

    main(args.src, args.dst, args.letters)

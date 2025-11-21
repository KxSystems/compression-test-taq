import logging
from datetime import datetime
from typing import List

import pyarrow as pa
import pyarrow.compute as pc

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

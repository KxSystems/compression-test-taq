#!/usr/bin/env python3

"""
Script to parse NYSE TAQ PSV files, transform data using PyArrow,
and persist to a hive-partitioned Parquet dataset.

Environment variables:
    SYMBOLSTOREDAS      PartitionColumn or RowGroup
    MINROWGROUPSIZE     If SYMBOLSTOREDAS=RowGroup then only row groups of size at least MINROWGROUPSIZE will be created
    COMPRESSION         Compression algorithm to be used when persisting data, e.g. ZSTD
    COMPRESSION_LEVEL   Level of compression, e.g. 10
    PAGE_SIZE           Page size as power of 2 between 12 and 20. Value e.g. 17 means 128KB.
                        The pyarrow default is 1 MB page size which corresponds to PAGE_SIZE value 20
"""

import os
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Final, List, Dict, Union
from functools import partial

from toolz import pipe

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.dataset as ds
import pyarrow.parquet as pq

import table_converters as conv

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

MASTERRENAME: Dict = {
    'Symbol': 'sym',
    'Security_Description': 'description',
    'CUSIP': 'cusip',
    'Security_Type': 'securityType',
    'SIP_Symbol': 'SIPSymbol',
    'Old_Symbol': 'oldSym',
    'Test_Symbol_Flag': 'testSymFlag',
    'Listed_Exchange': 'ex',
    'Tape': 'tap',
    'Unit_Of_Trade': 'unit',
    'Round_Lot': 'roundLot',
    'NYSE_Industry_Code': 'NYSEIndustryCode',
    'Shares_Outstanding': 'sharesOutstanding',
    'Halt_Delay_Reason': 'haltDelayReason',
    'Specialist_Clearing_Agent': 'specialistClearingAgent',
    'Specialist_Clearing_Number': 'specialistClearingNumber',
    'Specialist_Post_Number': 'specialistPostNumber',
    'Specialist_Panel': 'specialistPanel',
    'TradedOnNYSEMKT': 'tradedOnNYSEMKT',
    'TradedOnNASDAQBX': 'tradedOnNASDAQBX',
    'TradedOnNSX': 'tradedOnNSX',
    'TradedOnFINRA': 'tradedOnFINRA',
    'TradedOnISE': 'tradedOnISE',
    'TradedOnEdgeA': 'tradedOnEdgeA',
    'TradedOnEdgeX': 'tradedOnEdgeX',
    'TradedOnNYSETexas': 'tradedOnNYSETexas',
    'TradedOnNYSE': 'tradedOnNYSE',
    'TradedOnArca': 'tradedOnArca',
    'TradedOnNasdaq': 'tradedOnNasdaq',
    'TradedOnCBOE': 'tradedOnCBOE',
    'TradedOnPSX': 'tradedOnPSX',
    'TradedOnBATSY': 'tradedOnBATSY',
    'TradedOnBATS': 'tradedOnBATS',
    'TradedOnIEX': 'tradedOnIEX',
    'Tick_Pilot_Indicator': 'tickPilotIndicator',
    'Effective_Date': 'effectiveDate',
    'TradedOnLTSE': 'tradedOnLTSE',
    'TradedOnMEMX': 'tradedOnMEMX',
    'TradedOnMIAX': 'tradedOnMIAX'
}

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

TRADERENAME:Dict = {
    'Time': 'time',
    'Exchange': 'ex',
    'Symbol': 'sym',
    'Sale Condition': 'cond',
    'Trade Volume': 'size',
    'Trade Price': 'price',
    'Trade Stop Stock Indicator': 'stop',
    'Trade Correction Indicator': 'corr',
    'Sequence Number': 'seq',
    'Trade Id': 'tradeId',
    'Source of Trade': 'source',
    'Trade Reporting Facility': 'tradeReportingFacility',
    'Participant Timestamp': 'participantTimestamp',
    'Trade Reporting Facility TRF Timestamp': 'tradeReportingFacilityTRFTimestamp',
    'Trade Through Exempt Indicator': 'tradeThroughExemptIndicator'
}

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

QUOTERENAME : Dict = {
    'Time': 'time',
    'Exchange': 'ex',
    'Symbol': 'sym',
    'Bid_Price': 'bid',
    'Bid_Size': 'bsize',
    'Offer_Price': 'ask',
    'Offer_Size': 'asize',
    'Quote_Condition': 'cond',
    'Sequence_Number': 'seq',
    'National_BBO_Ind': 'nationalBBOInd',
    'FINRA_BBO_Indicator': 'finraBBOIndicator',
    'FINRA_ADF_MPID_Indicator': 'finraADFMPIDIndicator',
    'Quote_Cancel_Correction': 'corr',
    'Source_Of_Quote': 'source',
    'Retail_Interest_Indicator': 'retailInterestIndicator',
    'Short_Sale_Restriction_Indicator': 'shortSaleRestrictionIndicator',
    'LULD_BBO_Indicator': 'LULDBBOIndicator',
    'SIP_Generated_Message_Identifier': 'SIPGeneratedMessageIdentifier',
    'National_BBO_LULD_Indicator': 'NationalBBOLULDIndicator',
    'Participant_Timestamp': 'ParticipantTimestamp',
    'FINRA_ADF_Timestamp': 'FINRAADFTimestamp',
    'FINRA_ADF_Market_Participant_Quote_Indicator': 'FINRAADFMarketParticipantQuoteIndicator',
    'Security_Status_Indicator': 'securityStatusIndicator'
}

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

# --- Main Processing ---
def get_write_options(sort_idx: int) -> Dict[str, Union[str, int]]:
    """Get file write options (e.g. compression algorithm) based on environment variables.
    """
    compression = os.getenv('COMPRESSION')
    write_kwargs = {}
    if compression:
        logging.info(f"Setting parquet compression to {compression}")
        write_kwargs['compression'] = compression

    compression_level = os.getenv('COMPRESSION_LEVEL')
    if compression_level:
        logging.info(f"Setting parquet compression level to {compression_level}")
        write_kwargs['compression_level'] = int(compression_level)

    write_kwargs['sorting_columns'] = [pq.SortingColumn(sort_idx)]

    page_size = os.getenv('PAGE_SIZE')
    if page_size:
        ps =  2 ** int(page_size)
        if ps > 1024*1024:
            logging.warning(f"Page size value larger than 1 MB: {ps}")
        logging.info(f"Setting parquet page size to {ps}")
        write_kwargs['data_page_size'] = ps

    return write_kwargs

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
    logging.info(f"  Parsing file {file_path}")

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

def persist_rowgroup_per_symbol(table: pa.Table, table_output_path: Path,
                              parquet_options: Dict[str, Union[str, int]]) -> None:
    """Persists a Pyarrow table to a date-partitioned (following Hive format) Parquet dataset
    in which each row group belong to a Symbol
    Args:
        table: The table to persist
        table_output_path: The root directory for the output Parquet dataset.
        parquet_options: Parquet format options
    """
    if len(table) == 0:
        logging.info("  No rows after converting. Nothing to save.")
        return

    logging.info(f"  Saving {len(table)} rows")

    minrowgroupsize=0 if os.getenv('MINROWGROUPSIZE') is None else int(os.getenv('MINROWGROUPSIZE'))
    symbols = table.column("sym")
    date = table.column("date")[0].as_py().strftime('%Y-%m-%d') # TODO: make it more robust
    table = table.drop(['date'])
    # partition_schema=pa.schema([('date', pa.date32())])
    # Group consecutive same symbols
    os.makedirs(f"{table_output_path}/date={date}", exist_ok=True)
    with pq.ParquetWriter(f"{table_output_path}/date={date}/part-0.parquet", table.schema,
                          **parquet_options) as writer:
        start_idx = 0
        current_symbol = symbols[0]

        for i, symbol in enumerate(symbols):
            if symbol != current_symbol and i - start_idx > minrowgroupsize:
                # Write row group for previous symbol
                writer.write_table(table.slice(start_idx, i - start_idx), row_group_size=64 * 1024 * 1024)
                start_idx = i
                current_symbol = symbol

        # Write the final row group
        writer.write_table(table.slice(start_idx))

    logging.info(f"  Successfully wrote data to {table_output_path}")

def persistHive(table: pa.Table, table_output_path: Path,
            parquet_options: Dict[str, Union[str, int]]) -> None:
    """Persists a Pyarrow table to a Hive-partitioned Parquet dataset.
    Args:
        table: The table to persist
        table_output_path: The root directory for the output Parquet dataset.
        parquet_options: Parquet format options
    """
    if len(table) == 0:
        logging.info("  No rows after converting. Nothing to save.")
        return

    logging.info(f"  Saving {len(table)} rows")

    partition_schema=pa.schema([('date', pa.date32()), ('sym', pa.string())])
    ds.write_dataset(
        table,
        base_dir=table_output_path,
        format='parquet',
        partitioning=ds.partitioning(partition_schema, flavor='hive'),
        max_partitions=15000,
        existing_data_behavior='overwrite_or_ignore',
        file_options=ds.ParquetFileFormat().make_write_options(**parquet_options),
        preserve_order=True # Assumes original data is sorted by Time
    )

    logging.info(f"  Successfully wrote data to {table_output_path}")

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
            first_letter_filter = partial(conv.letter_filter, start_char, end_char)
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

    # no compression for the small master table
    master = parse_and_convert(master_file, MASTER_SCHEMA, [first_letter_filter])
    if includetestsymbols:
        master_extra_conv = extra_conv = IDENTITY
    else:
        test_symbols = master['Symbol'].filter(master['Test_Symbol_Flag'])
        master_extra_conv = lambda t: t.filter(pc.invert(t['Test_Symbol_Flag']))
        extra_conv = partial(conv.test_symbol_filter, test_symbols)

    master_conv= [master_extra_conv, conv.symbol_conv,
                  partial(conv.convert_date_strings_to_date32, ['Effective_Date']),
                  partial(conv.add_date_column, date), partial(conv.rename, MASTERRENAME)]
    master= pipe(master, *master_conv)
    parquet_options_master = {'compression': 'none'}
    if len(master) == 0:
        logging.info("  No rows after converting. Nothing to save. exiting")
        sys.exit()
    logging.info(f"  Saving {len(master)} rows")
    ds.write_dataset(
                master,
                base_dir=dst / 'master',
                format='parquet',
                partitioning=ds.partitioning(pa.schema([('date', pa.date32())]), flavor='hive'),
                existing_data_behavior='overwrite_or_ignore',
                file_options=ds.ParquetFileFormat().make_write_options(**parquet_options_master),
            )
    logging.info(f"  Successfully wrote data to {dst}/master")
    del master

    # Process quote files
    logging.info("Processing quote tables")
    quote_files = list(src.glob(f"SPLITS_US_ALL_BBO_[{letters}]_{datestr}.psv")) # first letter filter happens here
    quote_conv = [extra_conv, conv.symbol_conv,
            partial(conv.trim_dict_encode, ['FINRA_BBO_Indicator']),
            partial(conv.convert_time_strings_to_time64, ['Time', 'Participant_Timestamp', 'FINRA_ADF_Timestamp']),
            partial(conv.add_date_column, date), partial(conv.rename, QUOTERENAME)]
    parquet_options_quote = get_write_options(QUOTE_SCHEMA.get_field_index('TIME'))

    symbolstoredas = os.getenv('SYMBOLSTOREDAS')
    if symbolstoredas is None or symbolstoredas.upper() == "PARTITIONCOLUMN":
        for file_path in quote_files:
            persistHive(parse_and_convert(file_path, QUOTE_SCHEMA, quote_conv), dst / 'quote', parquet_options_quote)
    elif symbolstoredas.upper() == "ROWGROUP":
        quote_tables = [parse_and_convert(file_path, QUOTE_SCHEMA, quote_conv) for file_path in quote_files]
        quote = pa.concat_tables(quote_tables)
        del quote_tables
        persist_rowgroup_per_symbol(quote, dst / 'quote', parquet_options_quote)
        del quote
    else:
        logging.error("Unknown value for SYMBOLSTOREDAS environment variable: {symbolstoredas}") # TODO: Do this check earlier
        sys.exit(2)

    # Process trade files
    logging.info("Processing trade tables")
    trade_file = f"{src}/EQY_US_ALL_TRADE_{datestr}.psv"
    trade_conv = [first_letter_filter, extra_conv, conv.symbol_conv,
        partial(conv.trim_dict_encode, ['Sale Condition']),
        partial(conv.convert_time_strings_to_time64, ['Time', 'Participant Timestamp', 'Trade Reporting Facility TRF Timestamp']),
        partial(conv.add_date_column, date), partial(conv.rename, TRADERENAME)]
    parquet_options_trade = get_write_options(TRADE_SCHEMA.get_field_index('TIME'))
    trade = parse_and_convert(trade_file, TRADE_SCHEMA, trade_conv)
    if symbolstoredas is None or symbolstoredas.upper() == "PARTITIONCOLUMN":
        persistHive(trade, dst / 'trade', parquet_options_trade)
    else:
        persist_rowgroup_per_symbol(trade, dst / 'trade', parquet_options_trade)

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

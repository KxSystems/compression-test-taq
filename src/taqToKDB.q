//
// Script to parse NYSE TAQ PSV files, transform data
// and persist to a date-partitioned kdb+ database.
//
// Environment variables:
//   Compression related parameters: https://code.kx.com/q/kb/file-compression/#compression-parameters
//    LOGICAL_BLOCK_SIZE    Logical block size for the compression
//    COMPRESSION           Compression algorithm to be used when persisting data, e.g. ZSTD
//    COMPRESSION_LEVEL     Level of compression, e.g. 10
//
// Improvement of tq.q available at https://github.com/KxSystems/kdb-taq
// Improvements include:
//    * k code is rewritten to q
//    * destination directory is not hardcoded
//    * new parameter to filter on the first letter of the Symbol
//    * improved error handling
//    * code quality improvements
//    * option to drop test Symbols
//    * columns are written in parallel
//    * support of batch processing for smaller memory usage


\l src/log.q

if[(4.1>.z.K); .qlog.error "kdb+ 4.1 is required";exit 1];
USAGE: "usage: q ", string[.z.f], " [-help] -date DATE -src SRC [-dst DST] [-batchsize N] [-letters START-END] [-includetestsymbols]\n\n",
  "Parses NYSE TAQ PSV files and persists the content into a partitioned kdb+ database."
ko: key o: first each .Q.opt .z.x
if[`help in ko; -1 USAGE; exit 0]


/ Table master: EQY_US_ALL_REF_MASTER_*.csv
MASTERSCHEMA: ([
  sym:"*";
  description:"*";
  cusip:"S";
  securityType:"S";
  SIPSymbol:"S";
  oldSym:"S";
  testFlag:"B";
  ex:"C";
  tape:"C";
  unit:"H";
  roundLot:"H";
  NYSEIndustryCode:"S";
  sharesOutstanding:"F";
  haltDelayReason:"C";
  specialistClearingAgent:"S";
  specialistClearingNumber:"S";
  specialistPostNumber:"H";
  specialistPanel:"C";
  tradedOnNYSEMKT:"B";
  tradedOnNASDAQBX:"B";
  tradedOnNSX:"B";
  tradedOnFINRA:"B";
  tradedOnISE:"B";
  tradedOnEdgeA:"B";
  tradedOnEdgeX:"B";
  tradedOnNYSETexas:"B";
  tradedOnNYSE:"B";
  tradedOnArca:"B";
  tradedOnNasdaq:"B";
  tradedOnCBOE:"B";
  tradedOnPSX:"B";
  tradedOnBATSY:"B";
  tradedOnBATS:"B";
  tradedOnIEX:"B";
  tickPilotIndicator:"C";
  effectiveDate:"D";
  tradedOnLTSE:"B";
  tradedOnMEMX:"B";
  tradedOnMIAX:"B"
  ])

/ Exchange ID to Exchange name mapping
EXNAMES: ([A: "NYSE American"; B: "NASDAQ OMX BX"; C: "NYSE National"; D: "FINRA Alternative Display Facility";
  I: "International Securities Exchange"; J: "Cboe EDGA Exchange"; K: "Cboe EDGX Exchange";
  L: "Long-Term Stock Exchange"; M: "Chicago Stock Exchange";
  N: "New York Stock Exchange"; P: "NYSE Arca"; S: "Consolidated Tape System"; T: "NASDAQ Stock Market";
  Q: "NASDAQ Stock Exchange"; V: "The Investors' Exchange"; W: "Chicago Broad Options Exchange";
  X: "NASDAQ OMX PSX"; Y: "Cboe BYX Exchange"; Z: "Cboe BZX Exchange"])

/ Table trade: EQY_US_ALL_TRADE_*.csv
TRADESCHEMA: ([
  time:"N";
  ex:"C";
  sym:"*";
  cond:"S";
  size:"I";
  price:"E";
  stop:"S";
  corr:"H";
  seq:"I";
  tradeId:"J";
  source:"C";
  tradeReportingFacility:"S";
  participantTimestamp:"N";
  tradeReportingFacilityTRFTimestamp:"N";
  tradeThroughExemptIndicator:"B"
  ])

/ Table quote: splits_us_all_bbo_*[0-9]_*.csv
QUOTESCHEMA: ([
  time:"N";
  ex:"C";
  sym:"*";
  bid:"E";
  bsize:"I";
  ask:"E";
  asize:"I";
  cond:"C";
  seq:"I";
  nationalBBOInd:"C";
  finraBBOIndicator:"C";
  finraADFMPIDIndicator:"C";
  corr:"C";
  source:"C";
  retailInterestIndicator:"C";
  shortSaleRestrictionIndicator:"C";
  LULDBBOIndicator:"C";
  SIPGeneratedMessageIdentifier:"N";
  nationalBBOLULDIndicator:"C";
  participantTimestamp:"N";
  FINRAADFTimestamp:"N";
  FINRAADFMarketParticipantQuoteIndicator:"C";
  securityStatusIndicator:"C"
  ])


getCompParam:{[]
  algomap: ("NONE"; "QIPC"; "GZIP"; "SNAPPY"; "LZ4"; "ZSTD")!0 1 2 3 4 5i;
  compalgo: upper getenv `COMPRESSION;
  if[count compalgo;
    if[not compalgo in key algomap;
      .qlog.error "Unsupported compression algorithm: ", compalgo;
      exit 6];
    :("I"$getenv `LOGICAL_BLOCK_SIZE; algomap compalgo; "I"$getenv `COMPRESSION_LEVEL)];
  3#0i
  }

symbolConv: {
  update `$"."^sym from x}  / replace whitespace by dot

parseAndConvert: {[schema; conv; fileName:`C]
  .qlog.info "  Parsing file ", fileName;
  raw: flip key[schema]!value flip(value schema; enlist"|") 0:hsym `$fileName;
  .qlog.info "  Converting";
  conv raw
  }

genericUpsert:{[iter; path:`s; tab]
	iter[{[path;tab;c] .Q.dd[path;c] upsert tab c}[path;tab]; cols tab];
	}

enumAndSave: {[t; dst:`s; tableName:`s; saveDotD:`b; date:`C]
  path: .Q.par[dst;"D"$date;tableName];
  if[saveDotD; .Q.dd[path;`.d] set cols t];
  genericUpsert[peach; path; .Q.en[dst] t];
  }

psym: {[c:`s; x:`s]
  if[null @[@[;c;`p#];x;`];
    broken:x where not(x?x)=til count x@:where not=':[x@:c];
    .qlog.error "parted attribute cannot be applied on ", string[c], " due to ", "," sv string broken]
  }

batchProcess: {[schema; conv; dst:`s; tableName:`s; date:`C; rows]
  $[FirstRow; [
    t: conv flip key[schema]!(value schema; "|") 0:1_rows; / drop header
    enumAndSave[t; dst; tableName; 1b; date];
    FirstRow:: 0b;
  ]; [
    t: conv flip key[schema]!(value schema; "|") 0:rows;
    if[count t; enumAndSave[t; dst; tableName; 0b; date]];
  ]
  ]
  };

process: {[date:`C; dst:`s; tableName:`s; schema; conv; batchsize: `i; saveDotD:`b; fileName:`C]
  $[null batchsize; [
    t: parseAndConvert[schema; conv; fileName];
    .qlog.info "  Enumerating and saving ", string[count t], " rows";
    enumAndSave[t; dst; tableName; saveDotD; date]];[
    .qlog.info "  Starting batch processing file ", fileName;
    FirstRow:: 1b;
    .Q.fsn[batchProcess[schema; conv; dst; tableName; date]; hsym `$fileName; batchsize];
    ]]
  .qlog.info "  Data successfully persisted";
  }

testSymbolFilter: {[testSymbols:`S; t]
  ?[t;enlist (not; (in; `sym; enlist testSymbols));0b;()]
  }

main: {[date:`C; src:`C; dst; letters:`C; includetestsymbols:`b; batchsize: `i]
  startTime: .z.p;
  if[any (count key .Q.par[dst; "D"$o`date]@) each `master`quote`trade;
    .qlog.error "Destination directories exist. Clean up and rerun the script";
    exit 7];

  .qlog.info "Saving exchange names...";
  .Q.dd[dst; `exnames] set (raze string key EXNAMES)!`$value EXNAMES; / convert keys to characters

  letterFilter: $[count letters; {
    select from y where sym[;0] within x}[letters except "-"]; ::];
  compparam: getCompParam[]; / check compression parameters before persisting anything

  .qlog.info "Processing master table...";
  M: src, "/EQY_US_ALL_REF_MASTER_", date, ".psv";
  master: parseAndConvert[MASTERSCHEMA;letterFilter; M];
  (masterExtraConv; extraConv): $[includetestsymbols; (::; ::); [
    testSymbols: asc first flip symbolConv select sym from master where testFlag;
    (?[;enlist (not; `testFlag);0b;()]; testSymbolFilter[testSymbols])]];

  convMaster: symbolConv masterExtraConv@;
  enumAndSave[convMaster[master]; dst; `$"master/"; 1b; date];

  .z.zd: compparam; / apply compression to quote and trade
  / We apply first letter filter in file selection
  quotePattern: "splits_us_all_bbo_[", $[count letters;lower letters;"a-z"], "]_", date, ".psv";
  F: key hsym`$src;
  Q: (src, "/"),/: string asc F where (lower F) like quotePattern;
  if[0<count Q;
    .qlog.info "Processing quote tables...";
    @[count[Q]#0b;0;:;1b] process[date; dst; `quote; QUOTESCHEMA; extraConv symbolConv@; batchsize]' Q;
    .qlog.info "  Adding parted attribute...";
    psym[`sym; .Q.par[dst; "D"$date; `quote]]];

  .qlog.info "Processing trade table...";
  T: src, "/EQY_US_ALL_TRADE_", date, ".psv";
  process[date; dst; `trade;TRADESCHEMA;extraConv symbolConv letterFilter@; batchsize; 1b; T];
  .qlog.info "  Adding parted attribute...";
  psym[`sym; .Q.par[dst; "D"$date; `trade]];

  .qlog.info "\nAll processing completed in ", 2_string .z.p - startTime;
  }


if[not `date in ko;
  -1 USAGE;
  .qlog.error "'date' parameter was not provided";
  exit 2];

if[not `src in ko;
  -1 USAGE;
  .qlog.error "'src' parameter was not provided";
  exit 3];

if[(`letters in ko) and not o[`letters] like "?-?";
  .qlog.error "Invalid letter parameter. Must be in form START-END, for example A-K, got ", o[`letters];
  exit 4]


batchsize: $[not `batchsize in ko; 0Ni; () ~ o`batchsize; 10000000i; "I"$ o`batchsize]

main[o`date; o`src; hsym `kdbDB^`$o`dst; o `letters; `includetestsymbols in ko; batchsize]

if[not `debug in ko; exit 0]

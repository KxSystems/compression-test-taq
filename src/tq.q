// Improvement of tq.q available at https://github.com/KxSystems/kdb-taq
// Improvements include:
//    * k code is rewritten to q
//    * destination directory is not hardcoded
//    * new parameter to filter on the first letter of the Symbol
//    * improved error handling
//    * code quality improvements


\l src/log.q

if[(4.1>.z.K); .qlog.error "kdb+ 4.1 is required";exit 1];
USAGE: "usage: q ", string[.z.f], " [-help] -src SRC [-dst DST] [-letters START-END]\n\n",
  "Parses NYSE TAQ PSV files and persists the content into a partitioned kdb+ database."
ko: key o: first each .Q.opt .z.x

if[`help in ko; -1 USAGE; exit 0];
if[not `src in ko;
  -1 USAGE;
  .qlog.error "'src' parameter was not provided";
  exit 2];
SRC: hsym `$o`src
DST: hsym `kdbDB^`$o`dst

if[(`letters in ko) and not o[`letters] like "?-?";
  .qlog.error "Invalid letter parameter. Must be in form START-END, for example A-K, got ", o[`letters];
  exit 2]

LETTERS: o[`letters]

TRADESCHEMA: ([
  Time:"N";
  Exchange:"C";
  Symbol:"*";
  SaleCondition:"S";
  TradeVolume:"I";
  TradePrice:"E";
  TradeStopStockIndicator:"S";
  TradeCorrectionIndicator:"H";
  SequenceNumber:"I";
  TradeId:"*";
  SourceofTrade:"C";
  TradeReportingFacility:"S";
  ParticipantTimestamp:"N";
  TradeReportingFacilityTRFTimestamp:"N";
  TradeThroughExemptIndicator:"B"
  ])

QUOTESCHEMA: ([
  Time:"N";
  Exchange:"C";
  Symbol:"*";
  BidPrice:"F";
  BidSize:"I";
  OfferPrice:"F";
  OfferSize:"I";
  QuoteCondition:"C";
  SequenceNumber:"I";
  NationalBBOInd:"C";
  FINRABBOIndicator:"C";
  FINRAADFMPIDIndicator:"C";
  QuoteCancelCorrection:"C";
  SourceOfQuote:"C";
  RetailInterestIndicator:"C";
  ShortSaleRestrictionIndicator:"C";
  LULDBBOIndicator:"C";
  SIPGeneratedMessageIdentifier:"N";
  NationalBBOLULDIndicator:"N";
  ParticipantTimestamp:"C";
  FINRAADFTimestamp:"C";
  FINRAADFMarketParticipantQuoteIndicator:"C";
  SecurityStatusIndicator:"C"
  ])

letterConv: $[`letters in ko; {select from y where Symbol[;0] within x}[LETTERS except "-"]; ::]
symbolConv: {update `$"."^Symbol from x}  / replace whitespace by dot

psym: {[c:`s; x:`s]
  if[null @[@[;c;`p#];x;`];
    broken:x where not(x?x)=til count x@:where not=':[x@:c];
    .qlog.error "parted attribute cannot be applied on ", string[c], " due to ", "," sv string broken]
  }

getPart: {[dir:`s;tableName:`s;fileName:`s]
  .Q.par[dir;"D"$-8#first "." vs string fileName;tableName] / get rid of extension then get last 8 characters
  }

process: {[tableName:`s;schema;conv;op;fileName:`s]
  p: .Q.dd[getPart[DST;tableName;fileName];`];
  fullFileName: .Q.dd[SRC;fileName];
  .qlog.info "  Parsing file ", 1_string fullFileName;
  raw: (value schema; enlist"|") 0:fullFileName;
  .qlog.info "  Renaming and converting";
  t: conv flip key[schema]!value flip raw;
  .qlog.info "  Enumerating and saving ", string[count t], " rows";
  .[p;();op;.Q.en[DST] t];
  .qlog.info "  Successfully wrote data to ", 1_string p;
  }


conv: symbolConv letterConv@

quotePattern: "splits_us_all_bbo_[", $[`letters in ko;lower LETTERS;"a-z"], "]_*[0-9].psv"
Q: asc F where (lower F:key SRC) like quotePattern
if[0<count Q;
  .qlog.info "Processing quote tables...";
  processFn: process[`quote;QUOTESCHEMA;conv];
  processFn[:; first Q];
  processFn[,] each 1_Q;
  .qlog.info "  Adding parted attribute...";
  psym[`Symbol] each distinct getPart[DST;`quote] each Q]

T: F where lower[F] like "eqy_us_all_trade_[0-9]*.psv"
.qlog.info "Processing trade tables..."
process[`trade;TRADESCHEMA;conv;:] each T
.qlog.info "  Adding parted attribute..."
psym[`Symbol] each distinct getPart[DST;`trade] each T

.qlog.info "\nAll processing complete."
if[not `debug in ko; exit 0]

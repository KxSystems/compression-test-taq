// Improvement of tq.q available at https://github.com/KxSystems/kdb-taq
// Improvements include:
//    * k code is rewritten to q
//    * destination directory is not hardcoded
//    * new parameter to filter on the first letter of the Symbol
//    * improved error handling
//    * code quality improvements


\l src/log.q

if[(4.1>.z.K); .qlog.error "kdb+ 4.1 is required";exit 1];
USAGE: "usage: q ", string[.z.f], " [-help] -src SRC [-dst DST] [-letters START..END]\n\n",
  "Parses NYSE TAQ PSV files and persists the content into a partitioned kdb+ database."
ko: key o: first each .Q.opt .z.x

if[`help in ko; -1 USAGE; exit 0];
if[not `src in ko; .qlog.error USAGE; exit 2];
SRC: hsym `$o`src
DST: hsym `kdbDB^`$o`dst

letterConv: $[`letter in ko; [
  LETTER: o`letter;
  if[not LETTER like "?..?";
    .qlog.error "Invalid letter parameter. Must be in form START..END, for example A..K, got ", LETTER;
    exit 2];
  {select from y where Symbol[;0] within x}[LETTER except "."]]; ::];


symbolConv: {update `$"."^Symbol from x}  / replace whitespace by dot

psym: {[c:`s; x:`s]
  if[null @[@[;c;`p#];x;`];
    broken:x where not(x?x)=til count x@:where not=':[x@:c];
    .qlog.error "parted attribute cannot be applied on ", string[c], " due to ", "," sv string broken]
  }

getPart: {[dir:`s;tableName:`s;fileName:`s]
  .Q.par[dir;"D"$-8#string fileName;tableName]
  }

process: {[tableName:`s;colNames:`S;colTypes;conv;op;fileName:`s]
  p: .Q.dd[getPart[DST;tableName;fileName];`];
  fullFileName: .Q.dd[SRC;fileName];
  .qlog.info "Processing file ", 1_string fullFileName;
  / load and drop last line
  raw: -1 _ colTypes 0:fullFileName;
  / rename, convert and enumerate
  t: .Q.en[DST] conv flip colNames!value flip raw;
  / save
  .[p;();op;t];
  }

th:`Time`Exchange`Symbol`SaleCondition`TradeVolume`TradePrice`TradeStopStockIndicator,
  `TradeCorrectionIndicator`SequenceNumber`TradeId`SourceofTrade`TradeReportingFacility,
  `ParticipantTimestamp`TradeReportingFacilityTRFTimestamp`TradeThroughExemptIndicator;
tf:("NC*SIESHI*CSNNB";enlist"|")

qh:`Time`Exchange`Symbol`BidPrice`BidSize`OfferPrice`OfferSize`QuoteCondition,
  `SequenceNumber`NationalBBOInd`FINRABBOIndicator`FINRAADFMPIDIndicator,
  `QuoteCancelCorrection`SourceOfQuote`RetailInterestIndicator,
  `ShortSaleRestrictionIndicator`LULDBBOIndicator`SIPGeneratedMessageIdentifier,
  `NationalBBOLULDIndicator`ParticipantTimestamp`FINRAADFTimestamp,
  `FINRAADFMarketParticipantQuoteIndicator`SecurityStatusIndicator
qf:("NC*FIFICICCCCCCCCCCNNCC";enlist"|")
conv: symbolConv letterConv@

Q: asc F where (lower F:key SRC) like "splits_us_all_bbo_*[0-9].psv"
if[0<count Q;
  .qlog.info "Processing quote tables...";
  process[`quote;qh;qf;conv;:] first Q;
  process[`quote;qh;qf;conv;,] each 1_Q;
  .qlog.info "Adding parted attribute...";
  psym[`Symbol] each distinct getPart[DST;`quote] each Q]

T: F where lower[F] like "eqy_us_all_trade_[0-9]*.psv"
.qlog.info "Processing trade tables..."
process[`trade;th;tf;conv;:] each T
.qlog.info "Adding parted attribute..."
psym[`Symbol] each distinct getPart[DST;`trade] each T

if[not `debug in ko; exit 0]

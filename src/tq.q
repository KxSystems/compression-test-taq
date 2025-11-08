// Improvement of tq.q available at https://github.com/KxSystems/kdb-taq
// Improvements include:
//    * k code is rewritten to q
//    * destination directory is not hardcoded
//    * new parameter to filter on the first letter of the Symbol
//    * improved error handling
//    * code quality improvements


\l src/log.q

if[(4.1>.z.K); .qlog.error "kdb+ 4.1 is required";exit 1];
USAGE: "usage: q ", string[.z.f], " [-help] -src SRC [-dst DST] [-letters START-END] -skiptestsymbols\n\n",
  "Parses NYSE TAQ PSV files and persists the content into a partitioned kdb+ database."
ko: key o: first each .Q.opt .z.x
if[`help in ko; -1 USAGE; exit 0]


/ Table master: EQY_US_ALL_REF_MASTER_*.csv
MASTERSCHEMA: ([
  Symbol:"*";
  Security_Description:"*";
  CUSIP:"S";
  SecurityType:"S";
  SIPSymbol:"S";
  OldSymbol:"S";
  TestSymbolFlag:"B";
  ListedExchange:"C";
  Tape:"C";
  UnitOfTrade:"H";
  RoundLot:"H";
  NYSEIndustryCode:"S";
  SharesOutstanding:"F";
  HaltDelayReason:"C";
  SpecialistClearingAgent:"S";
  SpecialistClearingNumber:"S";
  SpecialistPost_Number:"H";
  SpecialistPanel:"C";
  TradedOnNYSEMKT:"B";
  TradedOnNASDAQBX:"B";
  TradedOnNSX:"B";
  TradedOnFINRA:"B";
  TradedOnISE:"B";
  TradedOnEdgeA:"B";
  TradedOnEdgeX:"B";
  TradedOnNYSETexas:"B";
  TradedOnNYSE:"B";
  TradedOnArca:"B";
  TradedOnNasdaq:"B";
  TradedOnCBOE:"B";
  TradedOnPSX:"B";
  TradedOnBATSY:"B";
  TradedOnBATS:"B";
  TradedOnIEX:"B";
  TickPilotIndicator:"C";
  Effective_Date:"D";
  TradedOnLTSE:"B";
  TradedOnMEMX:"B";
  TradedOnMIAX:"B"
  ])

/ Table trade: EQY_US_ALL_TRADE_*.csv
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
  TradeId:"J";
  SourceofTrade:"C";
  TradeReportingFacility:"S";
  ParticipantTimestamp:"N";
  TradeReportingFacilityTRFTimestamp:"N";
  TradeThroughExemptIndicator:"B"
  ])

/ Table quote: splits_us_all_bbo_*[0-9]_*.csv
QUOTESCHEMA: ([
  Time:"N";
  Exchange:"C";
  Symbol:"*";
  BidPrice:"E";
  BidSize:"I";
  OfferPrice:"E";
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

symbolConv: {update `$"."^Symbol from x}  / replace whitespace by dot

psym: {[c:`s; x:`s]
  if[null @[@[;c;`p#];x;`];
    broken:x where not(x?x)=til count x@:where not=':[x@:c];
    .qlog.error "parted attribute cannot be applied on ", string[c], " due to ", "," sv string broken]
  }

getPart: {[dir:`s;tableName:`s;fileName:`s]
  .Q.par[dir;"D"$-8#first "." vs string fileName;tableName] / get rid of extension then get last 8 characters
  }

parseAndConvert: {[schema;conv;fileName:`s]
  fullFileName: .Q.dd[SRC;fileName];
  .qlog.info "  Parsing file ", 1_string fullFileName;
  raw: flip key[schema]!value flip(value schema; enlist"|") 0:fullFileName;
  .qlog.info "  Converting";
  conv raw
 }

enumAndSave: {[t; tableName:`s;op;fileName:`s]
  .qlog.info "  Enumerating and saving ", string[count t], " rows";
  p: .Q.dd[getPart[DST;tableName;fileName];`];
  .[p;();op;.Q.en[DST] t];
  .qlog.info "  Successfully wrote data to ", 1_string p
 }

process: {[tableName:`s; schema; conv; op; fileName:`s]
  t: parseAndConvert[schema; conv; fileName];
  enumAndSave[t; tableName; op; fileName]
  }

main: {[src; dst; letters; skiptestsymbols]
  F: key src;

  letterFilter: $[count letters; {select from y where Symbol[;0] within x}[letters except "-"]; ::];

  M: F where lower[F] like "eqy_us_all_ref_master_[0-9]*.psv";
  .qlog.info "Processing master tables...";
  masters: parseAndConvert[MASTERSCHEMA;letterFilter] each M;
  (masterExtraConv; extraConv): $[skiptestsymbols; [
    testSymbols: asc first flip symbolConv select Symbol from first[masters] where TestSymbolFlag; / TODO: avoid first
    (?[;enlist (not;`TestSymbolFlag);0b;()]; ?[;enlist (not; (in; `Symbol; enlist testSymbols));0b;()])];(::; ::)];

  convMaster: symbolConv masterExtraConv@;
  conv: extraConv symbolConv letterFilter@;

  (convMaster each masters) enumAndSave[; `master; :; ]' M;

  quotePattern: "splits_us_all_bbo_[", $[count letters;lower letters;"a-z"], "]_*[0-9].psv";
  Q: asc F where (lower F) like quotePattern;
  if[0<count Q;
    .qlog.info "Processing quote tables...";
    processFn: process[`quote;QUOTESCHEMA;conv];
    processFn[:; first Q];
    processFn[,] each 1_Q;
    .qlog.info "  Adding parted attribute...";
    psym[`Symbol] each distinct getPart[dst;`quote] each Q]

  T: F where lower[F] like "eqy_us_all_trade_[0-9]*.psv";
  .qlog.info "Processing trade tables...";
  process[`trade;TRADESCHEMA;conv;:] each T;
  .qlog.info "  Adding parted attribute...";
  psym[`Symbol] each distinct getPart[dst;`trade] each T;
  }


if[not `src in ko;
  -1 USAGE;
  .qlog.error "'src' parameter was not provided";
  exit 2];
SRC: hsym `$o`src
DST: hsym `kdbDB^`$o`dst

if[(`letters in ko) and not o[`letters] like "?-?";
  .qlog.error "Invalid letter parameter. Must be in form START-END, for example A-K, got ", o[`letters];
  exit 2]

main[SRC; DST; o `letters; `skiptestsymbols in ko]

.qlog.info "\nAll processing complete."
if[not `debug in ko; exit 0]

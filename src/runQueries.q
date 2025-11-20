\l src/log.q

if["" ~ getenv `FLUSH;
  .qlog.info "Environment variable FLUSH is not set. Maybe config/env was not loaded.";
  exit 2]

ko: key o: first each .Q.opt .z.x;

DB: o `db
PARQUET: upper[o `format] like "PARQUET*"
PARQUETROWGROUP: upper[o `format] ~ "PARQUET_ROWGROUP"

/ TODO: add error handling
loadHiveTable: {[res; dir]
  res cross $[all {x=key x} .Q.dd[dir] first c: key dir;
    ([] file: .Q.dd[dir] each c); [
    tmp: "S=;"0:";" sv string c;
    raze (enlist each flip enlist[tmp[0;0]]!enlist $[tmp[0;0]=`date;"D"$;`$] tmp 1) .z.s' .Q.dd[dir] each c
  ]]
  }

loadHiveDataset: {[db]
  tNames: key hsym `$db;
  tparts: loadHiveTable[enlist ()] each .Q.dd[hsym `$db] each tNames;
  tNames set' {tb.mkP ![x;(); 0b; enlist `file]!$[PARQUETROWGROUP; {(`T!([t:(:{x,'([]mySymbol:`$x`9Symbol9min)})!])):x}; ::] each pq peach last flip x} each tparts
  }

getDeviceOSX:{[db:`C]
  "disk0"  / TODO: Implement a proper solution
  }

getFilesystem: {[db:`C] first " " vs last system "df ", db}
getDevice:{[db:`C]
  if[.z.o=`m64;:getDeviceOSX[db]];

  fs: getFilesystem[db];
  if["overlay" ~ fs; :fs];   / Inside Docker, NYI
  if["disk" ~ last system "lsblk -o type ", fs; :fs];
  p: ssr[;"/dev/";""] fs;
  // disk is looked up from partition by e.g. /sys/class/block/nvme0n1p1
  if[not (`$p) in key `$":/sys/class/block";
    .qlog.warn "Unable to map partition ", p, " to a device";
    :""];
  l:first system "readlink /sys/class/block/", p;
  "/dev",deltas[-2#l ss "/"] sublist l
  }

iostatError: `kB_read`kB_wrtn`kB_sum!3#0Nj

getKBReadMac: {[device:`C]
  if[device ~ enlist ""; :iostatError];
  iostatcmd: "iostat -d -I ", device, " 2>&1"; // -I returns the MB read as last column
  r: @[system; iostatcmd; .qlog.error];
  if[not 0h ~ type r; :iostatError];
  @[iostatError;`kB_sum;:;1000*`long$"F"$l last where not "" ~/: l:" " vs last r]
  }

getKBReadLinux: {[device:`C]
  iostatcmd: "iostat -dk -o JSON ", device, " 2>&1";
  r: @[system; iostatcmd; .qlog.error];
  :$[0h ~ type r; [
  	iostats: @[; `disk] first @[; `statistics] first first first value flip value .j.k raze r;
  	$[count iostats; [m:exec `long$sum kB_read, `long$sum kB_wrtn from iostats;m,([kB_sum: sum m])]; iostatError]];
	iostatError]
  }

getKBRead: $[.z.o ~ `m64; getKBReadMac; getKBReadLinux]

runQuery: {[query:`C]
  ts: ();
  io: ();
  .qlog.info raze system getenv[`FLUSH], " ", DB;
  .qlog.info "Collecting garbage";
  .Q.gc[];
  .qlog.info "Running query: ", query;
  io,: getKBRead[Device]`kB_read;
  ts,: enlist system "ts ", query;
  io,: getKBRead[Device]`kB_read;

  .qlog.info "Collecting garbage";
  .Q.gc[];
  .qlog.info "Running query again";
  ts,: enlist system "ts ", query;
  io,: getKBRead[Device]`kB_read;

  .Q.gc[];
  .qlog.info "Running query third time";
  ts,: enlist system "ts ", query;
  io,: getKBRead[Device]`kB_read;

  resultH ,[;"\n"] SEP sv (compparm; string system "s"; string IDX; query), string ts[;0], (ts[;1] div 1000), 1 _ deltas io;
  IDX+:1;
  };

Device: getDevice[DB]
.qlog.info "Monitoring device ", Device

resFile: $[`result in key o; o `result; "result.psv"];
.qlog.info "saving results to ", resFile;
resultH: hopen ":", resFile;
SEP: "|"
resultH "compparam|threadcount|idx|query|run1|run2|run3|mem1kb|mem2kb|mem3kb|io1kb|io2kb|io3kb\n"
IDX:0

$[PARQUET; [
  tb:use`kx.pq.t;
  ([pq]):use`kx.pq;

  .qlog.info raze system getenv[`FLUSH], " ", DB;
  .qlog.info "Collecting garbage";
  .Q.gc[];

  .qlog.info "loading parquet dataset at ", DB;
  ios: getKBRead[Device]`kB_read;
  ts: system "ts loadHiveDataset DB";
  ioe: getKBRead[Device]`kB_read;
  compparm: "nyi_nyi_nyi";
  ];[
  .qlog.info "loading kdb DB ", DB;
  ios: getKBRead[Device]`kB_read;
  ts: system "ts .Q.lo[`$DB;0;0]";
  ioe: getKBRead[Device]`kB_read;

  compparmall: -21!hsym `$DB,"/",string[first key hsym `$DB],"/quote/Symbol";   // or assume that db dir name reflects compression
  compparm: $[count compparmall; "_" sv string @[;`logicalBlockSize`algorithm`zipLevel] compparmall; "0_0_0"];

  if[`encr in ko;
    .qlog.info "Loading encryption file ", o`encr;
    -36!@[; 0; hsym `$] ":" vs o`encr]]]

resultH ,[;"\n"] SEP sv (compparm; string system "s"; string IDX; "load/mmap DB"), string ts[0], 0Nj, 0Nj, (ts[1] div 1000), 0Nj, 0Nj, ioe - ios, 0Nj, 0Nj;
IDX+:1;

symFreq: eval parse "first flip key asc select count i by ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"]," from quote where date=min date";

aFreqSym: @[; floor 0.80 * count symFreq] symFreq;
anInfreqSym: @[; floor 0.2 * count symFreq] symFreq;
someSyms1: -20?symFreq; / should be symbols of various quote counts to force different execution times
someSyms2: -100?symFreq;
infreqIdList: @[; til[500] + count[symFreq] div 10] symFreq; / many, but small quote count symbols


runQuery "select from quote where date=min date, Time<0D10"; / Huge amount of data
runQuery "select from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = anInfreqSym, Time within 0D08:30 0D16:30";       / All data from one symbol

/ SourceofTrade is a string in parquet and a character in kdb+
runQuery "select date, Symbol, Time, TradePrice, TradeVolume, TradeStopStockIndicator, SaleCondition, Exchange from trade where date=min date, SourceofTrade ",  / selected fields only
  $[PARQUET; "~\\: enlist \"N\""; "=\"N\""];
runQuery "select Symbol, Time, MidPrice: (BidPrice + OfferSize) %2 from select from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = aFreqSym";
runQuery "select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = aFreqSym";

runQuery "select avgMidSize: avg (BidPrice + OfferPrice) % 2 from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = anInfreqSym";
runQuery "select avgSpread: avg OfferPrice - BidPrice by 0D00:10 xbar Time from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = aFreqSym";

runQuery "distinct select Symbol, Exchange from trade where TradeVolume > 700000";

runQuery "select weightedBidPice: BidSize wavg BidPrice, weightedOfferPice: OfferSize wavg OfferPrice by Symbol from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " in someSyms1";
runQuery "select weightedSpread: (BidSize + OfferSize) wavg OfferPrice - BidPrice from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = anInfreqSym";

runQuery "select Time, 20 mavg TradePrice from trade where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = aFreqSym";
runQuery "select 5 mavg (OfferPrice + BidPrice) % 2, 5 mavg OfferSize + BidSize by Symbol from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " in someSyms1";
runQuery "raze {select Symbol, 5 mavg (OfferPrice + BidPrice) %2, 5 mavg OfferSize + BidSize from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = x} peach someSyms1";

runQuery "select Time, sums TradeVolume from trade where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = aFreqSym";
/ Exchange is a string in parquet and a character in kdb+
runQuery "select Time, sums TradeVolume from trade where Exchange ",
  $[PARQUET; "~\\: enlist \"L\""; "= \"L\""];

runQuery "select Time, sums TradeVolume from trade where Exchange ",
 $[PARQUET; "~\\: enlist \"T\""; "= \"T\""];

runQuery "select from trade where TradeVolume = (max;TradeVolume) fby Exchange";
runQuery "select from quote where OfferPrice = (min;OfferPrice) fby ([] Exchange;Symbol)";

runQuery "ungroup select from (select SequenceNumberDecr: SequenceNumber where (<) prior SequenceNumber by ",$[PARQUETROWGROUP;"`$";""],"Symbol from trade) where 0< count each SequenceNumberDecr";

runQuery "select cnt: count i, sum TradeVolume by Exchange from trade where date=min date";

/ TradeStopStockIndicator is a string in parquet and a symbol in kdb+
runQuery "select o: first TradePrice, h: max TradePrice, l: min TradePrice, c: last TradePrice, s: sum TradeVolume by Symbol, 0D00:05 xbar Time from trade where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " in someSyms2, ",
  $[PARQUET; "0 < count each" ; "not null"], " TradeStopStockIndicator";

runQuery "select inbal: (BidSize - OfferSize) % BidSize + OfferSize by ", / no dot notation in parquet yet
   $[PARQUET; "minute: `minute$0D00:01 xbar Time"; "Time.minute"], " from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = anInfreqSym";

runQuery "raze {select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = x} each infreqIdList";
runQuery "raze {select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = x} peach infreqIdList";
runQuery "raze {select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = x, 2000<BidSize+OfferSize} peach infreqIdList";

runQuery "raze {select first Symbol, wsumAsk:OfferSize wsum OfferPrice, wsumBid: BidPrice wsum BidSize, sdevask: sdev OfferSize, sdevbid:sdev BidPrice, corPrice:OfferPrice cor BidPrice, corSize: OfferSize cor BidSize from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = x} each infreqIdList";
runQuery "raze {select first Symbol, wsumAsk:OfferSize wsum OfferPrice, wsumBid: BidPrice wsum BidSize, sdevask: sdev OfferSize, sdevbid:sdev BidPrice, corPrice:OfferPrice cor BidPrice, corSize: OfferSize cor BidSize from quote where ", $[PARQUETROWGROUP; "mySymbol"; "Symbol"], " = x} peach infreqIdList";

if[PARQUETROWGROUP or not PARQUET; runQuery "select from trade where TradePrice = (min;TradePrice) fby Symbol"]; / fby clause does not work with partition column
if[not PARQUET; runQuery "select medMidSize: med (BidSize + OfferSize) % 2 from quote where Symbol=anInfreqSym"]; / function med is not supported

if[not PARQUET; runQuery "aj[`Symbol`Time; select Symbol, Time, TradePrice, TradeVolume, TradeStopStockIndicator, SaleCondition, Exchange from trade where date=min date, Symbol in someSyms1; select Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where date=min date]"]; / aj is slow in parquet
if[not PARQUET; runQuery "aj[`Symbol`Exchange`Time; select Symbol, Time, TradePrice, TradeVolume, TradeStopStockIndicator, SaleCondition, Exchange from trade where date=min date, TradeVolume>500000; select Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where date=min date]"]; / aj by a string key (Exchange) is not supported

if[not `debug in key o; exit 0];
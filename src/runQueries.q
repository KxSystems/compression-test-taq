\l src/log.q

o: first each .Q.opt .z.x;

result: ([] query: (); run1: `long$(); run2:`long$(); run3: `long$(); 
  mem1kb: `long$(); mem2kb:`long$(); mem3kb:`long$(); io1kb: `long$(); io2kb:`long$(); io3kb:`long$());

DB: o `db
.qlog.info "loading db ", DB
.Q.lo[`$DB;0;0]

if[`encr in key o; 
  .qlog.info "Loading encryption file ", o`encr;
  -36!@[; 0; hsym `$] ":" vs o`encr]

getPartition: {[]first " " vs last system "df ", DB}

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
Device: getDevice[DB]
.qlog.info "Monitoring device ", Device;


runQuery: {[query:`C]
  ts: ();
  io: ();
  .qlog.info raze system getenv[`FLUSH], " ", DB;
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
  ts,: enlist system "ts res:", query;
  io,: getKBRead[Device]`kB_read;

  `result insert enlist[enlist query], ts[;0], (ts[;1] div 1000), 1 _ deltas io;
  res
  };

runQuery "select from quote where i<500000000";
runQuery "select date, Symbol, Time, TradePrice, TradeVolume, TradeStopStockIndicator, SaleCondition, Exchange from trade where not null Time";
symFreq: first flip key asc runQuery "select nr: count i, avgMid: avg (BidPrice + OfferPrice) % 2 by Symbol from quote where date=min date";
aFreqSym: @[; floor 0.75 * count symFreq] symFreq;
runQuery "select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where Symbol=`", string aFreqSym;
anInfreqSym: @[; floor 0.2 * count symFreq] symFreq;
runQuery "select medMidSize: med (BidSize + OfferSize) % 2 from quote where Symbol=`", string anInfreqSym;
runQuery "distinct select Symbol, Exchange from trade where TradeVolume > 700000";
someSyms: @[; til[10] + count[symFreq] div 2] symFreq;

runQuery "select BidSize wavg BidPrice, OfferPrice wavg OfferSize from quote where Symbol in someSyms";
infreqIdList: @[; til[50] + count[symFreq] div 10] symFreq;
runQuery "raze {select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where Symbol=x} each infreqIdList";
runQuery "raze {select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where Symbol=x} peach infreqIdList";
runQuery "raze {select date, Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where Symbol=x, 4000<BidSize+OfferPrice} peach infreqIdList";
runQuery "raze {select first Symbol, wsumAsk:OfferPrice wsum OfferSize, wsumBid: BidSize wsum BidPrice, sdevask:sdev OfferSize, sdevbid:sdev BidPrice, corPrice:OfferPrice cor BidPrice, corSize: OfferSize cor BidSize from quote where Symbol=x} each infreqIdList";
runQuery "raze {select first Symbol, wsumAsk:OfferPrice wsum OfferSize, wsumBid: BidSize wsum BidPrice, sdevask:sdev OfferSize, sdevbid:sdev BidPrice, corPrice:OfferPrice cor BidPrice, corSize: OfferSize cor BidSize from quote where Symbol=x} peach infreqIdList";
runQuery "aj[`Symbol`Time; select Symbol, Time, TradePrice, TradeVolume, TradeStopStockIndicator, SaleCondition, Exchange from trade where date=min date, Symbol in someSyms; select Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where date=min date]";
runQuery "aj[`Symbol`Exchange`Time; select Symbol, Time, TradePrice, TradeVolume, TradeStopStockIndicator, SaleCondition, Exchange from trade where date=min date, TradeVolume>500000; select Symbol, Time, BidPrice, OfferPrice, BidSize, OfferSize, QuoteCondition, Exchange from quote where date=min date]";

resFile: $[`result in key o; o `result; "result.psv"];
.qlog.info "saving results to ", resFile;

compparmall: -21!hsym `$o[`db],"/",string[first date],"/quote/Symbol";   // or assume that db dir name reflects compression
compparm: $[count compparmall; "_" sv string @[;`logicalBlockSize`algorithm`zipLevel] compparmall; "0_0_0"];

(`$resFile) 0: "|" 0: ([] compparam: enlist compparm; threadcount: system "s") cross update idx: i from result;

if[not `debug in key o; exit 0];
\l src/log.q

if["" ~ getenv `FLUSH;
  .qlog.info "Environment variable FLUSH is not set. Maybe config/env was not loaded.";
  exit 2]

ko: key o: first each .Q.opt .z.x;

DB: o `db
PARAMDIR:  hsym `$o`paramdir
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
  tNames set' {tb.mkP ![x;(); 0b; enlist `file]!$[PARQUETROWGROUP; {(`T!([t:(:{x,'([]mysym:`$x`9sym9min)})!])):x}; ::] each pq peach last flip x} each tparts
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

runQuery: {[idx:`C; tags:`C; query:`C]
  if[not count query;
    resultH ,[;"\n"] SEP sv (compparm; string system "s"; idx; query), 9#enlist"";
    :();
  ]
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

  resultH ,[;"\n"] SEP sv (compparm; string system "s"; idx; tags; query), string ts[;0], (ts[;1] div 1000), 1 _ deltas io;
  };

Device: getDevice[DB]
.qlog.info "Monitoring device ", Device

resFile: $[`result in key o; o `result; "result.psv"];
.qlog.info "saving results to ", resFile;
if[not ()~key `$resFile: ":", resFile; hdel `$resFile];
resultH: hopen resFile;
SEP: "|"
resultH "compparam|threadcount|idx|tags|query|run1timeMS|run2timeMS|run3timeMS|run1memKB|run2memKB|run3memKB|run1ioKB|run2ioKB|run3ioKB\n"

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

  compparmall: -21!hsym `$DB,"/",string[first key hsym `$DB],"/quote/sym";   // or assume that db dir name reflects compression
  compparm: $[count compparmall; "_" sv string @[;`logicalBlockSize`algorithm`zipLevel] compparmall; "0_0_0"];

  if[`encr in ko;
    .qlog.info "Loading encryption file ", o`encr;
    -36!@[; 0; hsym `$] ":" vs o`encr]]]

resultH ,[;"\n"] SEP sv (compparm; string system "s"; string 0; "";"load/mmap DB"), string ts[0], 0Nj, 0Nj, (ts[1] div 1000), 0Nj, 0Nj, ioe - ios, 0Nj, 0Nj;

if["true" ~ lower getenv `QMAP;
  .qlog.info "Executing .Q.MAP[]";
  .Q.MAP[]]

.qlog.info "Loading parameters from ", 1_string PARAMDIR
aFreqSym: first `$read0 .Q.dd[PARAMDIR;`aFreqSym.txt]
anInfreqSym: first `$read0 .Q.dd[PARAMDIR;`anInfreqSym.txt]
someSyms1: `$read0 .Q.dd[PARAMDIR;`someSyms1.txt]
someSyms2: `$read0 .Q.dd[PARAMDIR;`someSyms2.txt]
infreqIdList: `$read0 .Q.dd[PARAMDIR;`infreqIdList.txt]

timeBuckets: ([preopen: 0D08:30; open: 0D09:05; morning: 0D12:30; afternoon: 0D16:30; close: 1D])

queryFile: o `queryfile;
.qlog.info "Loading and executing queries from ", queryFile;
{$["#" ~ first first x; ::; runQuery . value x]} each ("***";enlist "|") 0: `$queryFile; / skip comments

if[not `debug in key o; exit 0];
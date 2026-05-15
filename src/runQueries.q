system "l src/log.q"
system "l src/pivot.q" / This will be available as a KX module

if["" ~ getenv `FLUSH;
  .qlog.info "Environment variable FLUSH is not set. Maybe config/queryenv was not loaded.";
  exit 2]

ko: key o: first each .Q.opt .z.x;

DB: o `db
PARAMDIR: hsym `$o`paramdir
FORMAT: `$upper o `format
ENGINE: `$upper o `engine
QUERYOUTPUT: hsym `$o `queryoutput


QueryTable: ("****";enlist "|") 0: `$o `queryfile;
.qlog.info "Loading and executing queries from ", o `queryfile;
QueryMetaTable: `idx`querytag xcol ("**";enlist "|") 0: `$o `querymeta;

Tags: ("," vs o`tags) except enlist ""

if[not lower[getenv `EACHPEACH] in (""; "each"; "peach");
  .qlog.error "Invalid value for EACHPEACH environment variable. Allowed values are '', 'each' or 'peach'.";
  exit 3];
EACHPEACH: $["" ~ getenv `EACHPEACH; each; value lower getenv `EACHPEACH];

IOStatError: `kB_read`kB_wrtn`kB_sum!3#0Nj

getKBReadMac: {[device:`C]
  if[device ~ enlist ""; :IOStatError];
  iostatcmd: "iostat -d -I ", device, " 2>&1"; // -I returns the MB read as last column
  r: @[system; iostatcmd; .qlog.error];
  if[not 0h ~ type r; :IOStatError];
  @[IOStatError;`kB_sum;:;1000*`long$"F"$l last where not "" ~/: l:" " vs last r]
  }

getKBReadLinux: {[device:`C]
  iostatcmd: "iostat -dk -o JSON ", device, " 2>&1";
  r: @[system; iostatcmd; .qlog.error];
  :$[0h ~ type r; [
  	iostats: @[; `disk] first @[; `statistics] first first first value flip value .j.k raze r;
  	$[count iostats; [m:exec `long$sum kB_read, `long$sum kB_wrtn from iostats;m,([kB_sum: sum m])]; IOStatError]];
	IOStatError]
  }

getKBRead: $["false" ~ lower getenv `IOSTAT; {[x] IOStatError}; .z.o ~ `m64; getKBReadMac; getKBReadLinux]

getIdx: {[idx] $[10h ~ type idx; idx; string idx]}

writeRes: {[h; compparm:`C; idx:getIdx; tags; query:`C; (status:`C; ts:`N; memusage:`j; io:`J)]
  if[not 3 = count ts;
    .qlog.error "Three elapsed times are expected";
    ts: 3#ts];
  if[not 4 = count io;
    .qlog.error "Four IO numbers are expected";
    io: 4#io];
  h ,[;"\n"] SEP sv (compparm; string system "s"; idx; "," sv tags; query; status), string (`long$ts), (memusage div 1000), 1 _ deltas io;
  }

loadParquetDB: {[db: `C; rowgroup: `b; device: `C; writerFN]
  system "l src/loadHiveDataset.q";

  .qlog.info raze system getenv[`FLUSH], " ", db;
  .qlog.info "Collecting garbage";
  .Q.gc[];

  io: ();
  .qlog.info "loading parquet dataset at ", db;
  io,: getKBRead[device]`kB_read;
  s: .z.p;
  memusage: last first .Q.ts[loadHiveDataset; (db; rowgroup)];
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;
  writerFN[0; enlist ""; "load/mmap DB"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];

  exnames:: exec ex!`$name from exnames; / convert back to a map
  }

/////////////////// functions for in-memory tests ///////////////////

captureTableStats: {[tableStatsDir:`s; tName]
  tableStatsFile: .Q.dd[tableStatsDir; `$string[tName], ".yaml"];
  if[not ()~key tableStatsFile; hdel tableStatsFile];

  h: hopen tableStatsFile;
  h "name: ", (string tName), "\n";
  h "rowCount: ", (string count value tName), "\n";
  h "columnCount: ", (string count cols tName), "\n";
  h "columns: \n";
  {[h;tName;c]
    t: $[0h ~ type tName c; `string; key tName c];
    h "  - name: ", (string c), "\n";
    h "    type: ", (string t), "\n";
    h "    attr: ", (string meta[tName][c;`a]), "\n";
    }[h; tName] each cols tName;
  hclose h
  }

loadRootObjectsIntoMemory: {[db: `s]
  .qlog.info "loading root objects into memory ";
  c: key db;
  files: c where ({x ~ key x} .Q.dd[db]@) each c;
  db {[db; f]
    .qlog.info "loading object ", string[f], " into memory";
    f set (get[.Q.dd[db;f]] ::)}' files;
  }

loadKDBDBIntoMemory: ('[{[params]
  (db: `s; d: `d): 2#params;
  tbls: `master`trade`quote;
  if[3=count params; tbls: params 2];

  loadRootObjectsIntoMemory[db];
  dpath: .Q.dd[db; d];
  .qlog.info "loading tables in partition ", string[d], " into memory";
  .Q.dd[dpath] {[getPath; tName]
      .qlog.info "loading table ", string[tName], " into memory";
      tName set select from get[getPath tName] where i>-1;
      .qlog.info "Shape of ", string[tName], ": ", string[count value tName], " x ", string count cols tName; }' tbls;
  }; enlist])

sortTradeQuoteTables: {[sortCols]
  sortCols {[sortCols; tName]
    .qlog.info "sorting ", string[tName], " by ", $[0<type sortCols; "," sv ;] string sortCols;
    sortCols xasc tName
    }/: `trade`quote;
  }

addAttr: {[a]
  a {[a; tName]
    .qlog.info "Adding attribute ", string[a], " to sym of ", string[tName];
    update a#sym from tName }/: `quote`trade;
  }

loadKDBDBIntoMemoryTableDict: {[db: `s; d: `d]
  loadKDBDBIntoMemory[db;d;`master];

  .Q.dd[db;d] {[dpath; tName]
    .qlog.info "loading table ", string[tName], " into memory in table dictionary format";
    mappedT: get .Q.dd[dpath; tName];
    syms: exec asc distinct sym from mappedT;
    tName set (`u#syms)!mappedT {[t;s] delete sym from update `s#time from select from t where sym=s}/: syms}' `trade`quote;
  }

loadKDBPartitionIntoMemory: {[db: `s; device: `C; writerFN; d: `d; sortCols; attrOnSym:`s]
  .qlog.info "Loading kdb+ partition ", string[d], " into memory";
  io: (), getKBRead[device]`kB_read;
  s: .z.p;
  memusage: last first .Q.ts[loadKDBDBIntoMemory; (db;d)];
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;
  writerFN[0; enlist "load"; "load a partition into memory"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];

  if[count sortCols;
    io: (), getKBRead[device]`kB_read;
    s: .z.p;
    memusage: last first .Q.ts[sortTradeQuoteTables; enlist sortCols];
    ts: .z.p-s;
    io,: getKBRead[device]`kB_read;
    writerFN[-2; enlist "load"; "sort by time"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)]];

  if[not null attrOnSym;
    io: (), getKBRead[device]`kB_read;
    s: .z.p;
    memusage: last first .Q.ts[addAttr; enlist attrOnSym];
    ts: .z.p-s;
    io,: getKBRead[device]`kB_read;
    writerFN[-3; enlist "load"; "index"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];
    ];
  };

loadKDBPartitionIntoMemoryTableDict: {[db: `s; device: `C; writerFN; d: `d]
  .qlog.info "Loading kdb+ partition ", string[d], " into memory";
  io: (), getKBRead[device]`kB_read;
  s: .z.p;
  memusage: last first .Q.ts[loadKDBDBIntoMemoryTableDict; (db; d)];
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;
  writerFN[0; enlist "load"; "load first partition into memory"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];
  }

/////////////////////////////////////////////////////////

loadKDBDB: {[db: `C; device: `C; writerFN]
  io: ();
  .qlog.info "loading kdb DB ", db;
  if["true" ~ lower getenv `QMAP; loadcmd,:";.Q.MAP[]"];
  io,: getKBRead[device]`kB_read;
  s: .z.p;
  memusage: last first .Q.ts[.Q.lo; (db; 0b; 0)];
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;

  if[`encr in ko;
    .qlog.info "Loading encryption file ", o`encr;
    -36!@[; 0; hsym `$] ":" vs o`encr];

  writerFN[0; enlist "load"; "load/mmap DB"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];
  }

queryWrapper: $[ENGINE ~ `SQL;
  {[query; parameter] $[count parameter; ".s.sp[\"", query, "\"; enlist ", parameter, "]"; ".s.e \"", query, "\""]}; / for now, we accept a single parameter only
  {[x;] x}]

persistOutput: {[dir; res; idx:`C]
  if[not null dir;
    outFile: .Q.dd[dir; `$"queryoutput_", idx, ".csv"];
    origCols: cols res;
    res: .Q.id res;
    floatingCols: exec c from meta[res] where t in "ef";
    res: ![res; (); 0b; floatingCols!(each; .Q.f[6]; ) each floatingCols];
    outFile 0: .h.cd origCols xcol res;
  ];
  }

runQuery: {[db: `C; device: `C; writerFN; tags; idx:`C; querytags; query:`C; parameter:`C]
  if[ENGINE ~ `SQL; /This is needed due to a bug in kdb+ SQL engine where changing from data directory causes issues
    pwd: first system "pwd";
    system "cd ", db];
  query: trim query;
  parameter: trim parameter;
  if[not count query;
    writerFN[idx; querytags; query; ("emptyquery"; 3#0Nn; 0Nj; 4#0Nj)];
    :()];
  if["#" ~ first idx;
    writerFN[1_idx; querytags; query; ("skip"; 3#0Nn; 0Nj; 4#0Nj)];
    :()];
  if[count[tags] and 0 = count querytags inter tags;
    writerFN[idx; querytags; query; ("tagfiltered"; 3#0Nn; 0Nj; 4#0Nj)];
    :()];

  ts: io: ();
  .qlog.info raze system getenv[`FLUSH], " ", db;
  .qlog.info "Collecting garbage";
  .Q.gc[];
  .qlog.info "[", idx, "] Running query: ", query;
  io,: getKBRead[device]`kB_read;
  s: .z.p; / \ts does not collect memory usage of the secondary threads
  errormsg: @[system; "ts res:", queryWrapper[query; parameter]; ::];
  ts,: .z.p-s;
  if[10h ~ type errormsg;
    writerFN[idx; querytags; query; (errormsg; 3#0Nn; 0Nj; 4#0Nj)];
    :()];
  io,: getKBRead[device]`kB_read;
  .qlog.info "[", idx, "]   Shape of the result: ", string[count res], " x ", string count cols res;
  persistOutput[QUERYOUTPUT; 0!res; idx];
  delete res from `.;
  memusage: last errormsg;

  .qlog.info "[", idx, "]   Collecting garbage";
  .Q.gc[];
  .qlog.info "[", idx, "] Running query again";
  s: .z.p;
  errormsg: @[value; "res:", queryWrapper[query; parameter];::];
  ts,: .z.p-s;
  if[10h ~ type errormsg;
    writerFN[idx; querytags; query; (errormsg; ts[0], 2#0Nn; memusage; io, 2#0Nj)];
    :()];
  io,: getKBRead[device]`kB_read;
  delete res from `.;

  .Q.gc[];
  .qlog.info "[", idx, "] Running query third time";
  s: .z.p;
  errormsg: @[value; "res:", queryWrapper[query; parameter];::];
  ts,: .z.p-s;
  if[10h ~ type errormsg;
    writerFN[idx; querytags; query; (errormsg; ts, 0Nn; memusage; io, 0Nj)];
    :()];
  io,: getKBRead[device]`kB_read;
  delete res from `.;

  writerFN[idx; querytags; query; ("success"; ts; memusage; io)];
  if[ENGINE ~ `SQL; system "cd ", pwd];
  };

startTime: .z.p
Device: first system "./src/resolve_device.sh ", DB
.qlog.info "Monitoring device ", Device

resFile: $[`result in key o; o `result; "result.psv"];
.qlog.info "saving results to ", resFile;
if[not ()~key `$resFile: ":", resFile; hdel `$resFile];
resultH: hopen resFile;
SEP: "|"
resultH "compparam|threadcount|idx|tags|query|status|run1timeNS|run2timeNS|run3timeNS|run1memKB|run1ioKB|run2ioKB|run3ioKB\n"

$[FORMAT like "PARQUET*"; [
    compparm: "nyi_nyi_nyi";
    WriterFN:: writeRes[resultH; compparm];
    loadParquetDB[DB; FORMAT ~ `PARQUET_ROWGROUP; Device; WriterFN]
  ]; FORMAT = `KDBINMEMORY; [
    if[not `date in ko;
      .qlog.error "Date column is required for KDBINMEMORY format";
      exit 5];
    compparm: "0_0_0"; / data is not compressed in memory
    WriterFN:: writeRes[resultH; compparm];
    loadKDBPartitionIntoMemory[hsym `$DB; Device; WriterFN; "D"$o `date; `time; `];
  ]; FORMAT = `KDBINMEMORYGROUPED; [
    if[not `date in ko;
      .qlog.error "Date column is required for KDBINMEMORYGROUPED format";
      exit 5];
    compparm: "0_0_0"; / data is not compressed in memory
    WriterFN:: writeRes[resultH; compparm];
    loadKDBPartitionIntoMemory[hsym `$DB; Device; WriterFN; "D"$o `date; `time; `g];
  ]; FORMAT = `KDBINMEMORYPARTED; [
    if[not `date in ko;
      .qlog.error "Date column is required for KDBINMEMORYPARTED format";
      exit 5];
    compparm: "0_0_0"; / data is not compressed in memory
    WriterFN:: writeRes[resultH; compparm];
    loadKDBPartitionIntoMemory[hsym `$DB; Device; WriterFN; "D"$o `date; (); `p];
  ]; FORMAT = `KDBINMEMORYTABLEDICT; [
    if[not `date in ko;
      .qlog.error "Date column is required for KDBINMEMORYTABLEDICT format";
      exit 5];
    compparm: "0_0_0"; / data is not compressed in memory
    WriterFN:: writeRes[resultH; compparm];
    loadKDBPartitionIntoMemoryTableDict[hsym `$DB; Device; WriterFN; "D"$o `date];
    normalize: {cnt: count each x; ([] sym: where cnt) ,' raze x}; / convert table dictionary to normal table
  ]; FORMAT = `KDB; [
    compparmall: -21!hsym `$DB,"/",string[first key hsym `$DB],"/quote/sym";   // or assume that db dir name reflects compression
    compparm: $[count compparmall; "_" sv string @[;`logicalBlockSize`algorithm`zipLevel] compparmall; "0_0_0"];
    WriterFN:: writeRes[resultH; compparm];
    loadKDBDB[DB; Device; WriterFN]
  ]; [.qlog.error "Unknown format ", FORMAT; exit 1]]
if[not FORMAT ~ `KDBINMEMORYTABLEDICT;
  if[`tablestats in ko; captureTableStats[hsym `$o `tablestats] each `master`trade`quote]];
if[ENGINE ~ `SQL;
  .s.init[];
  .s.F[`stddev_pop]:.s.fx dev;
  .s.F[`stddev_samp]:.s.fx sdev;
  .s.F[`stddev]:.s.fx sdev;
  .s.F[`corr]:.s.fx {x cor y};
  .s.F[`median]:.s.fx med;
  .s.F[`exnames]:.s.fx{exnames x};
  ]

.qlog.info "Loading parameters from ", 1_string PARAMDIR
system "l src/getQueryParameters.q"
getQueryParameters PARAMDIR

if[not QueryTable[`idx] ~ QueryMetaTable`idx;
  .qlog.error "Index mismatch between the query and the query meta files";
  exit 4
  ]

queries: QueryTable lj `idx xkey QueryMetaTable;
queries: select idx, (except[;enlist ""] each "," vs' "," sv' flip (querytag; tags)), query, parameter from queries
(runQuery[DB; Device; WriterFN; Tags] . value@) each queries;

.qlog.info "Query benchmark completed in ", 2_string .z.p - startTime;
if[not `debug in key o; exit 0];
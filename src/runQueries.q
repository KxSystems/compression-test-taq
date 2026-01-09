system "l src/log.q"
system "l src/pivot.q" / This will be available as a KX module

if["" ~ getenv `FLUSH;
  .qlog.info "Environment variable FLUSH is not set. Maybe config/queryenv was not loaded.";
  exit 2]

ko: key o: first each .Q.opt .z.x;

DB: o `db
PARAMDIR: hsym `$o`paramdir
FORMAT: upper `$o `format

QueryTable: ("***";enlist "|") 0: `$o `queryfile;
.qlog.info "Loading and executing queries from ", o `queryfile;
QueryMetaTable: `idx`querytag xcol ("**";enlist "|") 0: `$o `querymetafile;

Tags: ("," vs o`tags) except enlist ""

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

getKBRead: $[.z.o ~ `m64; getKBReadMac; getKBReadLinux]

writeRes: {[h; compparm:`C; idx:`C; tags; query:`C; (status:`C; ts:`N; memusage:`j; io:`J)]
  if[not 3 = count ts;
    .qlog.error "Three elapsed times are expected";
    ts: 3#ts];
  if[not 4 = count io;
    .qlog.error "Four IO numbers are expected";
    io: 4#io];
  h ,[;"\n"] SEP sv (compparm; string system "s"; idx except "#"; "," sv tags; query; status), string (`long$ts), (memusage div 1000), 1 _ deltas io;
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
  memusage: last system "ts loadHiveDataset[", db, "; ", rowgroup, "]";
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;
  writerFN[string 0; enlist ""; "load/mmap DB"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];

  exnames:: exec ex!`$name from exnames; / convert back to a map
  }

loadKDBDBIntoMemory: {[db: `s]
  tablesBefore: tables[];
  c: key db;
  files: c where ({x ~ key x} .Q.dd[db]@) each c;
  db {[db; f]
    .qlog.info "loading object ", string[f], " into memory";
    f set (get[.Q.dd[db;f]] ::)}' files;
  dpath: .Q.dd[db] d: first c except files; / extract the first date's data only
  .qlog.info "loading tables in partition ", string[d], " into memory";
  .Q.dd[dpath] {[getPath; tName]
      .qlog.info "loading table ", string[tName], " into memory";
      tName set select from get[getPath tName] where i>-1 }' key dpath;

  newTables: tables[] except tablesBefore;
  {[tName]
    .qlog.info "sorting ", string[tName], " by  time";
    `time xasc tName
    } each newTables where `time in' cols each newTables;

  {[tName]
    .qlog.info "Adding groupped attribute to ", string[tName];
    update `g#sym from tName
    } each newTables;
  }

loadInMemKDBDB: {[db: `C; device: `C; writerFN]
  io: ();
  .qlog.info "loading kdb DB into memory from ", db;
  loadcmd: "ts loadKDBDBIntoMemory `$\":", db, "\"";
  io,: getKBRead[device]`kB_read;
  s: .z.p;
  memusage: last system loadcmd;
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;

  writerFN[string 0; enlist ""; "load/mmap DB"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];
  }
loadKDBDB: {[db: `C; device: `C; writerFN]
  io: ();
  .qlog.info "loading kdb DB ", db;
  loadcmd: "ts .Q.lo[`$\"", db, "\";0;0]";
  if["true" ~ lower getenv `QMAP; loadcmd,:";.Q.MAP[]"];
  io,: getKBRead[device]`kB_read;
  s: .z.p;
  memusage: last system loadcmd;
  ts: .z.p-s;
  io,: getKBRead[device]`kB_read;

  if[`encr in ko;
    .qlog.info "Loading encryption file ", o`encr;
    -36!@[; 0; hsym `$] ":" vs o`encr]

  writerFN[string 0; enlist ""; "load/mmap DB"; ("success"; ts, 2#0Nn; memusage; io, 2#0Nj)];
  }

runQuery: {[db: `C; device: `C; writerFN; tags; idx:`C; querytags; query:`C]
  query: trim query;
  if[not count query;
    writerFN[idx; querytags; query; ("emptyquery"; 3#0Nn; 0Nj; 4#0Nj)];
    :()];
  if["#" ~ first idx;
    writerFN[1_idx; querytags; query; ("skip"; 3#0Nn; 0Nj; 4#0Nj)];
    :()];
  if[count[tags] and 0 = count querytags inter tags;
    writerFN[1_idx; querytags; query; ("tagfiltered"; 3#0Nn; 0Nj; 4#0Nj)];
    :()];

  ts: io: ();
  .qlog.info raze system getenv[`FLUSH], " ", db;
  .qlog.info "Collecting garbage";
  .Q.gc[];
  .qlog.info "[", idx, "] Running query: ", query;
  io,: getKBRead[device]`kB_read;
  s: .z.p; / \ts does not collect memory usage of the secondary threads
  errormsg: @[system; "ts res:", query; ::];
  if[10h ~ type errormsg;
    writerFN[idx; querytags; query; (errormsg; 3#0Nn; 0Nj; 4#0Nj)];
    :()];
  ts,: .z.p-s;
  io,: getKBRead[device]`kB_read;
  .qlog.info "[", idx, "]   Shape of the result: ", string[count res], " x ", string count cols res;
  delete res from `.;
  memusage: last errormsg;

  .qlog.info "[", idx, "]   Collecting garbage";
  .Q.gc[];
  .qlog.info "[", idx, "] Running query again";
  s: .z.p;
  errormsg: @[value; "res:", query;::];
  if[10h ~ type errormsg;
    writerFN[idx; querytags; query; (errormsg; ts[0], 2#0Nn; memusage; io, 2#0Nj)];
    :()];
  ts,: .z.p-s;
  io,: getKBRead[device]`kB_read;
  delete res from `.;

  .Q.gc[];
  .qlog.info "[", idx, "] Running query third time";
  s: .z.p;
  errormsg: @[value; "res:", query;::];
  if[10h ~ type errormsg;
    writerFN[idx; querytags; query; (errormsg; ts, 0Nn; memusage; io, 0Nj)];
    :()];
  ts,: .z.p-s;
  io,: getKBRead[device]`kB_read;
  delete res from `.;

  writerFN[idx; querytags; query; ("success"; ts; memusage; io)];
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
    compparm: "0_0_0";
    WriterFN:: writeRes[resultH; compparm];
    loadInMemKDBDB[DB; Device; WriterFN]
  ]; [
    compparmall: -21!hsym `$DB,"/",string[first key hsym `$DB],"/quote/sym";   // or assume that db dir name reflects compression
    compparm: $[count compparmall; "_" sv string @[;`logicalBlockSize`algorithm`zipLevel] compparmall; "0_0_0"];
    WriterFN:: writeRes[resultH; compparm];
    loadKDBDB[DB; Device; WriterFN]
  ]]

.qlog.info "Loading parameters from ", 1_string PARAMDIR
system "l src/getQueryParameters.q"
getQueryParameters PARAMDIR

if[not QueryTable[`idx] ~ QueryMetaTable`idx;
  .qlog.error "Index mismatch between the query and the query meta files";
  exit 4
  ]

queries: QueryTable lj `idx xkey QueryMetaTable;
queries: select idx, (except[;enlist ""] each "," vs' "," sv' flip (querytag; tags)), query from queries
(runQuery[DB; Device; WriterFN; Tags] . value@) each queries;

.qlog.info "Query benchmark completed in ", 2_string .z.p - startTime;
if[not `debug in key o; exit 0];
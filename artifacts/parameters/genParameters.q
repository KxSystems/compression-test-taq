\l src/log.q

ko: key o: first each .Q.opt .z.x;

DB: o `db
DST: hsym `$o `dst

.qlog.info "loading kdb DB ", DB;
.Q.lo[`$DB;0;0]

symFreq: first flip key asc select count i by sym from quote where date=min date

aFreqSym: @[; floor 0.80 * count symFreq] symFreq;
.Q.dd[DST; `aFreqSym.txt] 0: enlist string aFreqSym

anInfreqSym: @[; floor 0.2 * count symFreq] symFreq;
.Q.dd[DST; `anInfreqSym.txt] 0: enlist string anInfreqSym

someSyms1: -20?symFreq; / should be symbols of various quote counts to force different execution times
.Q.dd[DST; `someSyms1.txt] 0: string someSyms1

someSyms2: -100?symFreq;
.Q.dd[DST; `someSyms2.txt] 0: string someSyms2

infreqIdList: @[; til[500] + count[symFreq] div 10] symFreq; / many, but small quote count symbols
.Q.dd[DST; `infreqIdList.txt] 0: string infreqIdList

exit 0
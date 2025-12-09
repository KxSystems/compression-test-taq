\l src/log.q

ko: key o: first each .Q.opt .z.x;

DB: o `db
DST: hsym `$o `dst

.qlog.info "loading kdb DB ", DB;
.Q.lo[`$DB;0;0]

symFreq: first flip key asc select count i by sym from quote where date=min date

mostFreqSym: last symFreq
.Q.dd[DST; `mostFreqSym.txt] 0: enlist string mostFreqSym

aFreqSym: @[; floor 0.80 * count symFreq] symFreq;
.Q.dd[DST; `aFreqSym.txt] 0: enlist string aFreqSym

anInfreqSym: @[; floor 0.2 * count symFreq] symFreq;
.Q.dd[DST; `anInfreqSym.txt] 0: enlist string anInfreqSym

twentySyms: -20?symFreq; / should be symbols of various quote counts to force different execution times
.Q.dd[DST; `twentySyms.txt] 0: string twentySyms

hundredSyms: -100?symFreq;
.Q.dd[DST; `hundredSyms.txt] 0: string hundredSyms

infreqIdList: @[; til[500] + count[symFreq] div 10] symFreq; / many, but small quote count symbols
.Q.dd[DST; `infreqIdList.txt] 0: string infreqIdList

exit 0
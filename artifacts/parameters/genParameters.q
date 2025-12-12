\l src/log.q

ko: key o: first each .Q.opt .z.x;

DB: o `db
DST: hsym `$o `dst

.qlog.info "loading kdb DB ", DB;
.Q.lo[`$DB;0;0]

symFreq: first flip key asc select count i by sym from quote where date=min date

mostFreqInstr: last symFreq
.Q.dd[DST; `mostFreqInstr.txt] 0: enlist string mostFreqInstr

aFreqInstr: @[; floor 0.80 * count symFreq] symFreq;
.Q.dd[DST; `aFreqInstr.txt] 0: enlist string aFreqInstr

anInfreqInstr: @[; floor 0.2 * count symFreq] symFreq;
.Q.dd[DST; `anInfreqInstr.txt] 0: enlist string anInfreqInstr

twentyInstrs: -20?symFreq; / should be symbols of various quote counts to force different execution times
.Q.dd[DST; `twentyInstrs.txt] 0: string twentyInstrs

hundredInstrs: -100?symFreq;
.Q.dd[DST; `hundredInstrs.txt] 0: string hundredInstrs

fivehundredInfreqInstrs: @[; til[500] + count[symFreq] div 10] symFreq; / many, but small quote count symbols
.Q.dd[DST; `fivehundredInfreqInstrs.txt] 0: string fivehundredInfreqInstrs

timeBuckets: ([preopen: 0D08:30; open: 0D09:05; morning: 0D12:30; afternoon: 0D16:30; close: 1D])
.Q.dd[DST; `timeBuckets.txt] 0: "=" sv' flip (string[key timeBuckets]; string value timeBuckets)

exit 0
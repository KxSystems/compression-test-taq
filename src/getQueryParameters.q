getQueryParameters: {[paramdir]
    `aFreqInstr set first `$read0 .Q.dd[paramdir;`aFreqInstr.txt];
    `mostFreqInstr set first `$read0 .Q.dd[paramdir;`mostFreqInstr.txt];
    `anInfreqInstr set first `$read0 .Q.dd[paramdir;`anInfreqInstr.txt];
    `twentyInstrs set `$read0 .Q.dd[paramdir;`twentyInstrs.txt];
    `hundredInstrs set `$read0 .Q.dd[paramdir;`hundredInstrs.txt];
    `fivehundredInfreqInstrs set `$read0 .Q.dd[paramdir;`fivehundredInfreqInstrs.txt];

    `timeBuckets set asc(!/) (`$; "N"$) @' flip  "=" vs/: read0 .Q.dd[paramdir; `timeBuckets.txt];
    `timeBucketsStep set `s#value[timeBuckets]!key timeBuckets;
    }
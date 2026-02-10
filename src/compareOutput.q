system "l src/log.q"

ko: key o: first each .Q.opt .z.x;

if[not all `querymeta`queryoutput1`queryoutput2 in ko;
    .qlog.error "Missing parameter(s): ", "," sv string `querymeta`queryoutput1`queryoutput2 except ko;
    exit 1];

querymeta: ("J*"; enlist "|")0: hsym `$o`querymeta / we only care about idx and tags
queryoutput1: hsym `$o`queryoutput1
queryoutput2: hsym `$o`queryoutput2

FLOATDIFFTHREASHOLD: 0.00005


tradeTypes: `time`ex`sym`cond`size`price`stop`corr`seq`tradeId`source`tradeReportingFacility`participantTimestamp`tradeReportingFacilityTRFTimestamp`tradeThroughExemptIndicator!"ncssieshijcsnnb"
quoteTypes: `time`ex`sym`bid`bsize`ask`asize`cond`seq`nationalBBOInd`finraBBOIndicator`finraADFMPIDIndicator`corr`source`retailInterestIndicator`shortSaleRestrictionIndicator`LULDBBOIndicator`SIPGeneratedMessageIdentifier`nationalBBOLULDIndicator`participantTimestamp`FINRAADFTimestamp`FINRAADFMarketParticipantQuoteIndicator`securityStatusIndicator!"ncseieiciccccccccccnncc"
types: tradeTypes, quoteTypes, ([mid: "f"; avgLiqWMid: "f"]),
 ([avgSpread: "f"; avgWeightedSpread: "f"; devSpread: "f"; maxSpread: "e"; minSpread: "e"]),
 ([weightedBidPrice: "f"; weightedOfferPrice: "f"]),
 ([movingLiqWMid: "f"; movingsize: "f"; movingvwap: "f"; tag: "s"; seqDecr: "i"]),
 ([timeBucket: "s"; cnt: "j"]),
 ([o: "e"; h: "e"; l: "e"; c: "e"; s: "i"]),
 ([minute: "u"; inbal: "f"]),
 ([wsumAsk: "f"; wsumBid: "f"; sdevasksize: "f"; sdevbid: "f"; corPrice: "f"; corSize: "f"]),
 ([pricegroup: "i"; FirstTime: "n"; LastTime: "n"; medMidSize: "f"; medSize: "f"; quotecond: "c"; quoteex: "c"])

compare: {[idx: `j; tags: `C]
    filename: `$"queryoutput_" , string[idx], ".csv";
    if[not filename in key queryoutput1;
        .qlog.error "Missing query output: ", string[filename], " from ", 1_string queryoutput1;
        :()];
    if[not filename in key queryoutput2;
        .qlog.error "Missing query output: ", string[filename], " from ", 1_string queryoutput2;
        :()];

    srct1: .Q.dd[queryoutput1; `$"queryoutput_" , string[idx], ".csv"];
    srct2: .Q.dd[queryoutput2; `$"queryoutput_" , string[idx], ".csv"];
    .qlog.info "Comparing tables with ", string[srct1], " and ", string srct2;
    t1cols: `$"," vs first system "head -n 1 ", 1_string srct1;
    t2cols: `$"," vs first system "head -n 1 ", 1_string srct2;
    t1: ("f"^types t1cols; enlist csv) 0: srct1;
    t2: ("f"^types t2cols; enlist csv) 0: srct2;

    if[ not count[t1] = count t2;
        .qlog.error "Different number of rows: ", string[count t1], " vs ", string count t2;
        'STOP];
    .qlog.info "Number of rows: \tOK";

    if[ not count[cols t1] = count cols t2;
        .qlog.error "Different number of columns: ", string[count cols t1], " vs ", string count cols t2;
        :()];
    .qlog.info "Number of columns: \tOK";


    if[ not (asc cols t1) ~ asc cols t2;
        .qlog.error "Different columns names: ", "," sv string cols[t1] except cols t2;
        :()];
    .qlog.info "Column names: \tOK";

    t2: cols[t1] xcols t2; / reorder columns to match t1

    if[not any "sortedoutput*" like/: "," vs tags;
        / sort based on some columns if they exist
        $[all `sym`ex`time in cols t1; [
          .qlog.info "Sorting by sym, ex, time";
          t1: `sym`ex`time xasc t1;
          t2: `sym`ex`time xasc t2];
          all `sym`timeBucket in cols t1; [
            .qlog.info "Sorting by sym, timeBucket";
            t1: `sym`timeBucket xasc t1;
            t2: `sym`timeBucket xasc t2];
            `sym in cols t1; [
              .qlog.info "Sorting by sym";
              t1: `sym xasc t1;
              t2: `sym xasc t2];
              `time in cols t1; [
                .qlog.info "Sorting by time";
                t1: `time xasc t1;
                t2: `time xasc t2]]];

    {[t1;t2;c]
        notok: not $[.Q.ty[t1 c] in "ef"; FLOATDIFFTHREASHOLD > abs t1[c] - t2 c; "C" ~ .Q.ty t1 c; t1[c] like' t2 c; t1[c] = t2 c];
        if[any notok;
            idx: first where notok;
            .qlog.error "Differ in column ", string[c], " e.g. index ", string[idx], ": ", string[t1[idx;c]], " vs ", string[t2[idx;c]];
            ;();
        ]}[t1;t2] each cols t1;

    .qlog.info "Content: \t\tOK";
  }

(compare . value@) each querymeta;

.qlog.info "ALL OK"

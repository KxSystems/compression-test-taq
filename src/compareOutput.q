system "l src/log.q"

src1: hsym `$first .z.x
src2: hsym `$last .z.x

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

compare: {[srct1; srct2]
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

    / sort based on some columns if they exist
    $[all `sym`ex`time in cols t1;
      [t1: `sym`ex`time xasc t1; t2: `sym`ex`time xasc t2];
      $[all `sym`timeBucket in cols t1;
        [t1: `sym`timeBucket xasc t1; t2: `sym`timeBucket xasc t2];
        $[`sym in cols t1; [t1: `sym xasc t1; t2: `sym xasc t2];
          if[`time in cols t1; [t1: `time xasc t1; t2: `time xasc t2]]]]];

    {[t1;t2;c]
        notok: not $[.Q.ty[t1 c] in "ef"; FLOATDIFFTHREASHOLD > abs t1[c] - t2 c; "C" ~ .Q.ty t1 c; t1[c] like' t2 c; t1[c] = t2 c];
        if[any notok;
            idx: first where notok;
            .qlog.error "Differ in column ", string[c], " e.g. index ", string[idx], ": ", string[t1[idx;c]], " vs ", string[t2[idx;c]];
            ;();
        ]}[t1;t2] each cols t1;

    .qlog.info "Content: \t\tOK";
  }

(.Q.dd[src1] each key src1) compare' (.Q.dd[src2] each key src2)

.qlog.info "ALL OK"

#!/usr/bin/env bash

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/common.sh"

: "${COMPPARAMS:?Error: COMPPARAMS not set.}"
if [[ ! "$COMPPARAMS" =~ ^[0-9_\ ]*$ ]]; then  # only numbers, underscores and spaces are allowed
  die "Invalid COMPPARAMS string. A valid COMPPARAMS example: \"17_0_0 17_2_5 17_3_0 17_4_5 17_5_1\"" 2
fi
read -ra COMPPARRAY <<< "$COMPPARAMS"

declare ENCR=""
if [[ $# -eq 2 ]]; then
  if [[ "$2" =~ ^[^:]+:[^:]+$ ]]; then
    readonly ENCR="-encr $2"
  else
    die "Invalid encryption format. Expected: file:password" 2
  fi
fi

readonly TIMESTAMP=$(date +%m%d_%H%M)
readonly RESULTDIR="results/${TIMESTAMP}"
mkdir -p $RESULTDIR

function get_column_stat () {
  echo "Generating column statistics..."
  $QEXEC ./src/columnStat.q -db "$DST/zd0_0_0" -tables trade,quote \
    -result ./${RESULTDIR}/columnStatUncompressed.psv -s ${COMPUTECOUNT} -q
}

readonly WRITETESTTABLE=trade   # Select a small and wide table

function test_write_times () {
  local outputname="$1"
  local scriptparam="$2"

  echo "Measuring write times..."
  WRITETESTDIR=${DST}/${outputname}
  mkdir -p ${RESULTDIR}/tmp
  for kdbdatedir in ${DST}/zd0_0_0/*; do
    [[ ! -d "$kdbdatedir" ]] && continue
    local kdbdate=$(basename $kdbdatedir)

    for compparam in ${COMPPARRAY[@]}; do
      echo "Testing compression $compparam"
      mkdir -p ${WRITETESTDIR}/${compparam}/${kdbdate}/${WRITETESTTABLE}

      $QEXEC ./src/compress.q -date $kdbdate -table ${WRITETESTTABLE} -compparam "${compparam}" \
        -src "${DST}/zd0_0_0" -dst "${WRITETESTDIR}/" -times ./${RESULTDIR}/tmp/${outputname}_${compparam}.psv $scriptparam \
        -syncdir $ENCR -s ${COMPUTECOUNT} -q

      rm -rf ${WRITETESTDIR}/${compparam}/${kdbdate}/${WRITETESTTABLE}
    done
  done

  rm -rf ${WRITETESTDIR}
  head -n 1 ./${RESULTDIR}/tmp/${outputname}_${COMPPARRAY[0]}.psv > ./${RESULTDIR}/${outputname}.psv
  for compparam in ${COMPPARRAY[@]}; do
    tail -n +2 ./${RESULTDIR}/tmp/${outputname}_${compparam}.psv >> ./${RESULTDIR}/${outputname}.psv
    rm ./${RESULTDIR}/tmp/${outputname}_${compparam}.psv
  done
}

function compress_tables () {
  echo "Generating compressed data in parallel..."

  for kdbdatedir in ${DST}/zd0_0_0/*; do
    [[ ! -d "$kdbdatedir" ]] && continue
    local kdbdate=$(basename $kdbdatedir)

    for compparam in ${COMPPARRAY[@]}; do
      echo "Testing compression ${compparam}..."

      if [ ${compparam} != "0_0_0" ]; then
        for TABLEDIR in $DST/zd0_0_0/$kdbdate/*; do
            TABLE="$(basename "$TABLEDIR")"
            echo "Compressing ${TABLE}..."
            mkdir -p $DST/zd${compparam}/$kdbdate/${TABLE}
            $QEXEC ./src/compress.q -date $(basename $kdbdate) -table $TABLE  -compparam ${compparam} \
              -src "${DST}/zd0_0_0" -dst "$DST/zd" -peach $ENCR -s $COMPUTECOUNT -q &
            cp "${TABLEDIR}"/.d $DST/zd${compparam}/$kdbdate/${TABLE}/
        done
        cp $DST/zd0_0_0/sym $DST/zd${compparam}
      fi
      wait
    done
  done

  sync $DST
}

function get_disk_usage () {
  echo "Calcuating disk usage..."
  local DISKRESUTLFILE=${RESULTDIR}/diskusage.psv
  echo "usage|compparam|date|table|column" > ${DISKRESUTLFILE}
  find $DST -type f -exec du -k {} + \
  | grep -e "/trade/" -e "/quote/" \
  | grep -v '\.d' \
  | sed -e "s|$DST\/zd||g" \
  | tr "\t/" "|" \
  >> ${DISKRESUTLFILE}
}

function test_queries () {
  echo "Measuring query times..."
  sudo tee /proc/sys/vm/max_map_count <<< 16777216 >/dev/null

  for compparam in ${COMPPARRAY[@]}; do
    echo "Testing compression ${compparam}..."  
    numactl -N 0 -m 0 ${QEXEC} ./src/runqueries.q -db $DST/zd${compparam} \
      -result ${RESULTDIR}/tmp/query_${compparam}.psv \
      $ENCR -s ${COREPERSOCKET} -q
  done

  sort -ur ./${RESULTDIR}/tmp/query_*.psv > ./${RESULTDIR}/query_summary.psv
}

readonly start=$(date +%s)

get_column_stat
test_write_times writetimes ""
# test_write_times writetimes_parallel "-peach"
compress_tables
get_disk_usage2
test_queries

readonly end=$(date +%s)
readonly duration=$((end - start))

echo "TAQ kdb+ compression test completd in ${duration} seconds."
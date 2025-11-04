#!/usr/bin/env bash

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/common.sh"

## Parsing the DATE from the input
DATE="${2:-$(date +"%Y%m%d")}"
if ! [[ "$DATE" =~ ^[0-9]{8}$ ]]; then
  echo "Error: DATE must be in YYYYMMDD format. Got: '$DATE'" >&2
  exit 1
fi
KDBDATE="${DATE:0:4}.${DATE:4:2}.${DATE:6:2}"

readonly valid_sizes=("full" "large" "medium" "small")

: "${SIZE:?Error: SIZE must be set to 'full', 'large', 'medium', or 'small'}"

if [[ ! " ${valid_sizes[*]} " =~ " ${SIZE} " ]]; then
    echo "Error: Unknown SIZE: $SIZE. Valid options are: ${valid_sizes[*]}" >&2
    exit 1
fi

case "$SIZE" in
  "full")   LETTERS='A-Z' ;;
  "large")  LETTERS='A-H' ;;
  "medium") LETTERS='I-I' ;;
  "small")  LETTERS='Z-Z' ;;
esac

function getFilename() {
    local type=$1 letter=$2
    echo "${type}_US_ALL_${letter}_${DATE}.gz"
}

readonly URLPREFIX="https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/"

function get_CSVs () {
  echo "Fetching gzipped CSV files..."
  mkdir -p ${CSVDIR}
  pushd ${CSVDIR}

  LETTERARRAY=($(eval echo {${LETTERS:0:1}..${LETTERS:2:1}}))
  for letter in ${LETTERARRAY[@]}; do
    qfname=$(getFilename "SPLITS" "BBO_${letter}")
    if [[ -f ${qfname%.*} ]]; then
      echo "${qfname} was already downloaded and unzipped. Skipping download."
    else
      wget -c "${URLPREFIX}${qfname}"
      echo "Unzipping downloaded file in the background"
      gunzip "${qfname}" &
    fi
  done

  local tfname=$(getFilename "EQY" "TRADE")
  if [[ -f ${tfname%.*} ]]; then
    echo "${tfname} was already downloaded and unzipped. Skipping download."
  else
    wget -c "${URLPREFIX}${tfname}"
    echo "Unzipping downloaded file"
    gunzip "${tfname}"
  fi

  local mfname=$(getFilename "EQY" "REF_MASTER")
  if [[ -f ${mfname%.*} ]]; then
    echo "${mfname} was already downloaded and unzipped. Skipping download."
  else
    wget -c "${URLPREFIX}${mfname}"
    echo "Unzipping downloaded file"
    gunzip "${mfname}"
  fi

  wait

  # TODO: add check if last line starts with 'END'
  echo "Removing last lines and adding proper extension"
  head -n -1 ${tfname%.*} > ${tfname%.*}.psv
  rm ${tfname%.*}
  head -n -1 ${mfname%.*} > ${mfname%.*}.psv
  rm ${mfname%.*}
  for letter in ${LETTERARRAY[@]}; do
    qfname=$(getFilename "SPLITS" "BBO_${letter}")
    head -n -1 ${qfname%.*} > ${qfname%.*}.psv
    rm ${qfname%.*}
  done

  popd
}

function generate_HDB () {
  if [[ ${FORMAT} == "parquet" ]]; then
    echo "Generating parquet dataset..."
    python3 ./src/parquet.py -src $CSVDIR -dst $DSTPARQUET/uncompressed -letters $LETTERS
  else
    echo "Generating kdb+ data (aka. HDB)..."
    $QEXEC ./src/tq.q -src $CSVDIR -dst $DSTKDB/zd0_0_0 -letters $LETTERS -s $COMPUTECOUNT -q
  fi
}

function cleanup_CSVs () {
  rm -rf ${CSVDIR}
}

echo "TAQ data capture started."

readonly start=$(date +%s)

get_CSVs
generate_HDB
cleanup_CSVs
readonly end=$(date +%s)

readonly duration=$((end - start))

echo "TAQ data capture completd in ${duration} seconds."
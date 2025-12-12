#!/usr/bin/env bash

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/common.sh"

readonly URLPREFIX="https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/"

function getFilename() {
    local type=$1 letter=$2
    echo "${type}_US_ALL_${letter}_${DATE}.gz"
}

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

echo "NYSE TAQ CSV capture started."
get_CSVs
readonly end=$(date +%s)
readonly duration=$((end - start))
echo "TAQ data capture completd in ${duration} seconds."
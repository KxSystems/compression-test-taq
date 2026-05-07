#!/usr/bin/env bash

set -euo pipefail

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/util.sh"

CSVDIR="$1"

readonly URLPREFIX="https://ftp.nyse.com/Historical%20Data%20Samples/DAILY%20TAQ/"

function getFilename() {
    local type=$1 letter=$2
    echo "${type}_US_ALL_${letter}_${DATE}.gz"
}

function get_CSVs () {
  echo "Fetching gzipped CSV files..."
  mkdir -p ${CSVDIR}
  pushd ${CSVDIR}

  LETTERS=$(get_letters $SIZE)
  LETTERARRAY=($(eval echo {${LETTERS:0:1}..${LETTERS:2:1}}))
  for letter in ${LETTERARRAY[@]}; do
    qfname=$(getFilename "SPLITS" "BBO_${letter}")
    if [[ -f ${qfname%.*} ]]; then
      echo "${qfname} was already downloaded and unzipped. Skipping download."
    else
      curl -C - -O "${URLPREFIX}${qfname}"
      echo "Unzipping downloaded file in the background"
      gunzip "${qfname}" &
    fi
  done

  local tfname=$(getFilename "EQY" "TRADE")
  if [[ -f ${tfname%.*} ]]; then
    echo "${tfname} was already downloaded and unzipped. Skipping download."
  else
    curl -C - -O "${URLPREFIX}${tfname}"
    echo "Unzipping downloaded file"
    gunzip "${tfname}"
  fi

  local mfname=$(getFilename "EQY" "REF_MASTER")
  if [[ -f ${mfname%.*} ]]; then
    echo "${mfname} was already downloaded and unzipped. Skipping download."
  else
    curl -C - -O "${URLPREFIX}${mfname}"
    echo "Unzipping downloaded file"
    gunzip "${mfname}"
  fi

  wait

  OS=$(uname)
  if [[ "$OS" == "Linux" ]]; then
    SEDOPTION="-i"
  elif [[ "$OS" == "Darwin" ]]; then
    SEDOPTION="-i ''"
  else
    echo "Unsupported OS: $OS"
    exit 1
  fi

  # TODO: add check if last line starts with 'END'
  echo "Removing last lines and adding proper extension"
  sed ${SEDOPTION} '$d' ${tfname%.*}
  mv ${tfname%.*} ${tfname%.*}.psv

  sed ${SEDOPTION} '$d' ${mfname%.*}
  mv ${mfname%.*} ${mfname%.*}.psv
  for letter in ${LETTERARRAY[@]}; do
    qfname=$(getFilename "SPLITS" "BBO_${letter}")
    sed ${SEDOPTION} '$d' ${qfname%.*}
    mv ${qfname%.*} ${qfname%.*}.psv
  done

  popd
}

echo "NYSE TAQ CSV capture started."
readonly start=$(date +%s)
get_CSVs
readonly end=$(date +%s)
readonly duration=$((end - start))
echo "TAQ data capture completed in ${duration} seconds."
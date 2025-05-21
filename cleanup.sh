#!/usr/bin/env bash

source ./common.sh

## Think twice before you delete the DB, it takes long to regenerate
echo "Cleaning up"
for compparam in ${COMPPARAMS[@]}; do
  rm -rfv $DST/zd${compparam}
done



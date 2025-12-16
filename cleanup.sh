#!/usr/bin/env bash

script_dir=$(dirname "${BASH_SOURCE[0]}")
source "${script_dir}/common.sh"

## Think twice before you delete the DB, it takes long to regenerate
echo "Cleaning up"
for compparam in ${COMPPARAMS[@]}; do
  rm -rfv $DSTKDB/zd${compparam}
done



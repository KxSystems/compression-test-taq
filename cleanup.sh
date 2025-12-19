#!/usr/bin/env bash

## Think twice before you delete the DB, it takes long to regenerate
echo "Cleaning up"
for compparam in ${COMPPARAMS[@]}; do
  rm -rfv $DSTKDB/zd${compparam}
done



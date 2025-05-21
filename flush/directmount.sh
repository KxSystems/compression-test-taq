#!/usr/bin/env bash

if [ $# -eq 0 ]; then
    error_handler "No directory specified. Usage: $0 <directory>"
fi

echo "Syncing $1 and flushing page cache"

if [ $(uname -s) = "Darwin" ];then
	sync $1; sudo purge
else
	sync $1; echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null
fi

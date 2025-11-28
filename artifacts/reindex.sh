#!/bin/bash

# simple script to populate the first column of a psv with 1,2,3, etc.

INPUT_FILE=$1
OUTPUT_FILE=$(mktemp)

head -n 1 "$INPUT_FILE" > "$OUTPUT_FILE"
tail -n +2 "$INPUT_FILE" | awk -F'|' -v OFS='|' '{$1 = NR; print}' >> "$OUTPUT_FILE"

mv $OUTPUT_FILE $INPUT_FILE
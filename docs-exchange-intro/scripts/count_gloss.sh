#!/bin/bash
# Count the number of glossary entries in the Glossary chapter.

YELLOW='\033[1;33m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

GLOSSARY_FILE="src/90-backmatter/20-glossary.md"
NUM_GLOSSARY=`grep -n '^\*\*[A-Za-z_ /()0-9-]*:\*\*' "$GLOSSARY_FILE" | wc -l`

# Strip leading whitespace from the count
NUM_GLOSSARY=$(echo "$NUM_GLOSSARY" | sed 's/^[ \t]*//')

echo "$NUM_GLOSSARY"



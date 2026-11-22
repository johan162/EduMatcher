#!/bin/bash
# Script to copy the artifacts to the johan162 site
# Remember to commit the changes and push them after running this script

set -euo pipefail # Exit on any error or uninitialized variable

DARK_GREEN='\033[0;32m'
GREEN='\033[1;32m'
DARK_RED='\033[0;31m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
DARK_YELLOW='\033[0;33m'
CYAN='\033[1;36m'
DARK_CYAN='\033[0;36m'
DARK_BLUE='\033[0;34m'
BLUE='\033[1;34m'
NC='\033[0m'

# Set SED_INLINE to the correct syntax if we are on Darwin of Linux
if [[ "$OSTYPE" == "darwin"* ]]; then
  SED_INLINE=(-i "")
else
  SED_INLINE=(-i)
fi

# Read the current version number only from 'version.toml' 
VERSION=$(grep '^version' version.toml | head -1 | cut -d'"' -f2)

# Define source and destination directories
SRC_DIR="dist"
DEST_DIR="../../johan162.github.io/exchange_intro"

# Check that the source and destination directories exist
if [ ! -d "$SRC_DIR" ]; then
  echo -e "${RED}Source directory $SRC_DIR does not exist.${NC}"
  exit 1
fi

if [ ! -d "$DEST_DIR" ]; then
  echo -e "${RED}Destination directory $DEST_DIR does not exist.${NC}"
  exit 1
fi

# Clean the destination directory before copying
rm -rf "$DEST_DIR"/*.pdf
rm -rf "$DEST_DIR"/*.epub
rm -rf "$DEST_DIR"/*.zip
rm -rf "$DEST_DIR"/parts-a4-pdf

# echo -e "${GREEN}Cleaned destination directory ${DEST_DIR}/${NC}"

# Copy the artifacts
echo -e "${DARK_YELLOW}Copying artifacts from ${CYAN}'${SRC_DIR}/'${DARK_YELLOW} to ${CYAN}'${DEST_DIR}/' ${DARK_YELLOW}...${NC}"
cp -r "$SRC_DIR"/* "$DEST_DIR"

echo -e "${DARK_YELLOW}Updating version to ${CYAN}${VERSION}${DARK_YELLOW}...${NC}"
sed "${SED_INLINE[@]}" -E "s/[0-9]+\.[0-9]+\.[0-9]+/${VERSION}/g" "$DEST_DIR/index.md"

echo -e "${GREEN}✓ Copy and update complete!${NC}"

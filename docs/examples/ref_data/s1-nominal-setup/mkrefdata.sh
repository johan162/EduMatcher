#!/usr/bin/env bash
exec "$(dirname "${BASH_SOURCE[0]}")/../mkrefdata_common.py" "$(dirname "${BASH_SOURCE[0]}")" "$@"

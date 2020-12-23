#!/bin/bash -e


SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"


mkdir -p $SCRIPT_DIR/bin

GOBIN=$SCRIPT_DIR/bin go install ./...

#!/bin/bash


SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"


echo BUILDING DEB PACKAGE...

(cd $SCRIPT_DIR && fakeroot dpkg-deb -b phenix-apps)

echo DONE BUILDING DEB PACKAGE

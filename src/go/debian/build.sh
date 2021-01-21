#!/bin/bash


SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APPS=$SCRIPT_DIR/..


which docker &> /dev/null
DOCKER=$?

if (( $DOCKER == 0 )); then
  echo "Docker detected, so Docker will be used to build golang-phenix-apps."

  (cd $APPS && $APPS/docker-build.sh)
else
  echo "Docker not detected, using natively installed Go."

  (cd $APPS && make install)
fi


echo COPYING FILES...

DST=$SCRIPT_DIR/golang-phenix-apps/usr

mkdir -p $DST

cp -r $APPS/bin $DST/

echo COPIED FILES


echo BUILDING DEB PACKAGE...

(cd $SCRIPT_DIR && fakeroot dpkg-deb -b golang-phenix-apps)

echo DONE BUILDING DEB PACKAGE

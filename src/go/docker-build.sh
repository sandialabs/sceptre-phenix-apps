#!/bin/bash -e


which docker &> /dev/null

if (( $? )); then
  echo "Docker must be installed (and in your PATH) to use this build script. Exiting."
  exit 1
fi


USER_UID=$(id -u)
USERNAME=builder


docker build -t golang-phenix-apps:builder -f - . <<EOF
FROM golang:1.14

RUN groupadd --gid $USER_UID $USERNAME \
  && useradd -s /bin/bash --uid $USER_UID --gid $USER_UID -m $USERNAME
EOF


echo BUILDING golang-phenix-apps...

docker run -it --rm -v $(pwd):/phenix-apps -w /phenix-apps -u $USERNAME \
  golang-phenix-apps:builder ./build.sh

echo DONE BUILDING golang-phenix-apps

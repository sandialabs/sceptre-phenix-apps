#!/bin/bash -e


which docker &> /dev/null

if (( $? )); then
  echo "Docker must be installed (and in your PATH) to use this build script. Exiting."
  exit 1
fi


USER_UID=$(id -u)
USERNAME=builder


docker build -t python-phenix-apps:builder -f - . <<EOF
FROM ubuntu:focal

RUN groupadd --gid $USER_UID $USERNAME \
  && useradd -s /bin/bash --uid $USER_UID --gid $USER_UID -m $USERNAME

ENV TZ=Etc/UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt update && apt install -y \
  apt-file \
  build-essential \
  debhelper \
  devscripts \
  dpkg-dev \
  fakeroot \
  python3 \
  python3-apt \
  python3-distro \
  python3-pip

RUN python3 -m pip install wheel2deb
EOF


echo PACKAGING python-phenix-apps...

docker run -it --rm -v $(pwd):/phenix-apps -w /phenix-apps -u $USERNAME python-phenix-apps:builder ./package.sh

echo DONE PACKAGING python-phenix-apps

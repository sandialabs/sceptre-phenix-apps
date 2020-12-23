#!/bin/bash -e

cat > wheel2deb.yml << EOF
.:
  maintainer_name: Bryan Richardson
  maintainer_email: bryan@activeshadow.com
EOF

# Build wheel for phenix-apps
python3 -m pip wheel .

# Convert all wheels to debian source packages
wheel2deb --map attrs=attr

# Call dpkg-buildpackages for each source package
wheel2deb build

rm -f *.whl
rm wheel2deb.yml

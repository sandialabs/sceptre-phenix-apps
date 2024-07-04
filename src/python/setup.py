#!/usr/bin/env python3

from setuptools import setup, find_packages

import phenix_apps


with open("README.md", "r") as fh:
    long_description = fh.read()


# Include app template files.
DATA = {
    'phenix_apps': [
        'apps/*/templates/*.mako',
        'apps/scorch/*/templates/*.mako',
    ],
}


ENTRIES = {
    'console_scripts' : [
        'phenix-app-caldera = phenix_apps.apps.caldera.caldera:main',
        'phenix-app-helics = phenix_apps.apps.helics.helics:main',
        'phenix-app-ot-sim = phenix_apps.apps.otsim.otsim:main',
        'phenix-app-protonuke = phenix_apps.apps.protonuke.protonuke:main',
        'phenix-app-sceptre = phenix_apps.apps.sceptre.sceptre:main',
        'phenix-app-wind-turbine = phenix_apps.apps.wind_turbine.wind_turbine:main',
        'phenix-app-wireguard = phenix_apps.apps.wireguard.wireguard:main',
        'phenix-scheduler-single-node = phenix_apps.schedulers.single_node.single_node:main',
        'phenix-scorch-component-art = phenix_apps.apps.scorch.art.art:main',
        'phenix-scorch-component-caldera = phenix_apps.apps.scorch.caldera.caldera:main',
        'phenix-scorch-component-cc = phenix_apps.apps.scorch.cc.cc:main',
        'phenix-scorch-component-collector = phenix_apps.apps.scorch.collector.collector:main',
        'phenix-scorch-component-ettercap = phenix_apps.apps.scorch.ettercap.ettercap:main',
        'phenix-scorch-component-hoststats = phenix_apps.apps.scorch.hoststats.hoststats:main',
        'phenix-scorch-component-iperf = phenix_apps.apps.scorch.iperf.iperf:main',
        'phenix-scorch-component-mm = phenix_apps.apps.scorch.mm.mm:main',
        'phenix-scorch-component-pcap = phenix_apps.apps.scorch.pcap.pcap:main',
        'phenix-scorch-component-qos = phenix_apps.apps.scorch.qos.qos:main',
        'phenix-scorch-component-rtds = phenix_apps.apps.scorch.rtds.rtds:main',
        'phenix-scorch-component-disruption = phenix_apps.apps.scorch.disruption.disruption:main',
        'phenix-scorch-component-snort = phenix_apps.apps.scorch.snort.snort:main',
        'phenix-scorch-component-tcpdump = phenix_apps.apps.scorch.tcpdump.tcpdump:main',
        'phenix-scorch-component-trafficgen = phenix_apps.apps.scorch.trafficgen.trafficgen:main',
        'phenix-scorch-component-vmstats = phenix_apps.apps.scorch.vmstats.vmstats:main',
    ]
}


setup(
    author          = 'Bryan Richardson, Active Shadow LLC',
    description     = 'User apps and schedulers for phenix orchestration',
    packages        = find_packages(),
    package_data    = DATA,
    entry_points    = ENTRIES,
    name            = 'phenix-apps',
    platforms       = 'Linux',
    python_requires = '>=3.8',
    url             = 'https://github.com/sandialabs/sceptre-phenix-apps/',
    version         = phenix_apps.__version__,

    classifiers = [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],

    install_requires = [
        'lxml~=4.9.2',
        'Mako~=1.1.3',
        'minimega',
        'python-box~=5.1.1',
        'elasticsearch~=8.12.0',
        'requests==2.31.0',
        'python-dateutil==2.8.2',
    ],

    long_description = long_description,
    long_description_content_type = "text/markdown",
)

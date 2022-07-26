from setuptools import setup, find_packages

import phenix_apps


with open("README.md", "r") as fh:
    long_description = fh.read()


# Include app template files.
DATA = {
    'phenix_apps': [
        'apps/*/templates/*.mako',
    ],
}


ENTRIES = {
    'console_scripts' : [
        'phenix-app-ot-sim = phenix_apps.apps.otsim.otsim:main',
        'phenix-app-protonuke = phenix_apps.apps.protonuke.protonuke:main',
        'phenix-app-wireguard = phenix_apps.apps.wireguard.wireguard:main',
        'phenix-scheduler-single-node = phenix_apps.schedulers.single_node.single_node:main',
        'phenix-scorch-component-art = phenix_apps.apps.scorch.art.art:main',
        'phenix-scorch-component-cc = phenix_apps.apps.scorch.cc.cc:main',
        'phenix-scorch-component-ettercap = phenix_apps.apps.scorch.ettercap.ettercap:main',
        'phenix-scorch-component-hoststats = phenix_apps.apps.scorch.hoststats.hoststats:main',
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
    python_requires = '>=3.7',
    url             = 'https://github.com/sandia-minimega/phenix-apps',
    version         = phenix_apps.__version__,

    classifiers = [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.7',
    ],

    install_requires = [
        'Mako~=1.1.3',
        'minimega',
        'python-box~=5.1.1',
    ],

    long_description = long_description,
    long_description_content_type = "text/markdown",
)

from setuptools import setup, find_packages

import phenix_apps


with open("README.md", "r") as fh:
    long_description = fh.read()


ENTRIES = {
    'console_scripts' : [
        'phenix-app-protonuke = phenix_apps.apps.protonuke.protonuke:main',
        'phenix-scheduler-single-node = phenix_apps.schedulers.single_node.single_node:main',
    ]
}


setup(
    author          = 'Bryan Richardson, Active Shadow LLC',
    description     = 'User apps and schedulers for phenix orchestration',
    entry_points    = ENTRIES,
    name            = 'phenix-apps',
    packages        = find_packages(),
    platforms       = 'Linux',
    python_requires = '>=3.7',
    url             = 'https://github.com/activeshadow/phenix-apps',
    version         = phenix_apps.__version__,

    classifiers = [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.7',
    ],

    install_requires = [
        'Mako~=1.1.3',
        'python-box~=5.1.1',
    ],

    long_description = long_description,
    long_description_content_type = "text/markdown",
)

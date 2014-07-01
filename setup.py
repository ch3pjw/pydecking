from setuptools import setup, find_packages

_NAME = 'pydecking'

import versioneer
versioneer.versionfile_source = 'decking/_version.py'
versioneer.versionfile_build = 'decking/_version.py'
versioneer.tag_prefix = ''
versioneer.parentdir_prefix = '{}-'.format(_NAME)

setup(
    name=_NAME,
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    description='An implementation of decking in Python',
    long_description=open('README.md').read(),
    author='Paul Weaver',
    author_email='paul@ruthorn.co.uk',
    url='https://github.com/ch3pjw/pydecking',
    packages=find_packages(),
    install_requires=(
        'PyYaml',
        'docker-py',
        'docopt',
        'blessings'
    ),
    extras_require={
        'dev': (
            'unittest2',
            'nose',
            'coverage',
        ),
    },
    entry_points={
        "console_scripts": (
            "decking = decking.main:main"
        )
    },
)

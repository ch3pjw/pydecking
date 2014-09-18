import re
from distutils.command.sdist import sdist as _sdist
from setuptools import setup, find_packages

_NAME = 'pydecking'

import versioneer
versioneer.versionfile_source = 'decking/_version.py'
versioneer.versionfile_build = 'decking/_version.py'
versioneer.tag_prefix = 'v'
versioneer.parentdir_prefix = '{}-'.format(_NAME)


def pep440_version(versioneer_version):
    parts = re.match(
        '(?P<number>[0-9.]+)'
        '(?:-(?P<distance>[1-9][0-9]*))?'
        '(?:-(?P<revision>g[0-9a-f]{7}))?'
        '(?:-(?P<dirty>dirty))?', versioneer_version
        ).groupdict()
    version = parts['number']
    if parts['distance']:
        version += '.post0.dev' + parts['distance']
    elif parts['dirty']:
        # If we're building from a dirty tree, make sure that
        # this is flagged as a dev version
        version += '.post0.dev0'

    return version


# Need this part to ensure the published version uses the pep440 version
class cmd_sdist(versioneer.cmd_sdist):
    def run(self):
        versions = versioneer.get_versions(verbose=True)
        self._versioneer_generated_versions = versions
        # unless we update this, the command will keep using the old version
        self.distribution.metadata.version = pep440_version(
            versions["version"])
        return _sdist.run(self)


cmdclass = versioneer.get_cmdclass()
cmdclass['sdist'] = cmd_sdist


setup(
    name=_NAME,
    version=pep440_version(versioneer.get_version()),
    cmdclass=cmdclass,
    description='An implementation of decking in Python',
    long_description=open('README.md').read(),
    author='Paul Weaver',
    author_email='paul@ruthorn.co.uk',
    url='https://github.com/ch3pjw/pydecking',
    packages=find_packages(),
    install_requires=(
        'PyYaml',
        'docker-py>=0.5.0',
        'docopt',
        'blessings',
        'cerberus'
    ),
    extras_require={
        'dev': (
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

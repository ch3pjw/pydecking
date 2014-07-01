from setuptools import setup, find_packages

setup(
    name='pydecking',
    version=0.01,
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
            'coverage'
        ),
    },
    entry_points={
        "console_scripts": (
            "decking = decking.main:main"
        )
    }
)

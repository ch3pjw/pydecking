"""
Usage:
    decking help
    decking build IMAGE [--config=CONFIG]
    decking create [--config=CONFIG]
    decking start [--config=CONFIG]
    decking stop [--config=CONFIG]
    decking restart [--config=CONFIG]
    decking status [--config=CONFIG]
    decking attach [--config=CONFIG]

Arguments:
    IMAGE               The name of the image to build according to the
                        directives located in the cluster configuration
                        file. To build all images, specify 'all'.

Options:
    --config=CONFIG     Define the file to read the cluster configuration
                        from. JSON and YAML formats are supported.
                        [default: decking.json]
"""

from __future__ import print_function

import sys
from decking.runner import DeckingRunner
from decking.terminal import Terminal
import yaml
import docker
from docopt import docopt, DocoptExit


def _read_config(opts):
    filename = opts["--config"]
    try:
        with open(filename) as f:
            return yaml.load(f)
    except IOError:
        raise IOError(
            "Could not open cluster configuration file " +
            filename
        )


def main():
    try:
        opts = docopt(__doc__)
    except DocoptExit as error:
        sys.exit(error.message)

    if opts["help"]:
        print(__doc__)
        sys.exit(0)

    try:

        decking_config = _read_config(opts)

        docker_client = docker.Client(
            base_url='unix://var/run/docker.sock', version='0.9.1', timeout=10)
        runner = DeckingRunner(decking_config, docker_client)

        if opts["start"]:
            runner.run_all()
        elif opts["create"]:
            if opts["IMAGE"] != 'all':
                raise NotImplementedError(
                    "Creation is currently only supported for 'all' images")
            runner.create_all()
        elif opts["build"]:
            runner.build_all()
        else:
            raise NotImplementedError(
                "This operation hasn't been implemented yet")

    except KeyboardInterrupt:
        Terminal().print_error("Operation interrupted by user")
    except Exception as error:
        Terminal().print_error(
            "Operation failed",
            error)


if __name__ == '__main__':
    main()

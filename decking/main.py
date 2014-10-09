"""
Usage:
    decking help
    decking build WHAT [--no-cache] [--config=CONFIG] [--debug]
    decking (push | pull) WHAT [REGISTRY] [--config=CONFIG] [--debug] [--allow-insecure]
    decking OPERATION CLUSTER [--config=CONFIG] [--debug]

decking image operations:
    WHAT            The image name found in the decking definition file,
                    or the cluster on which all images must be built.
                    To reference all images provide the literal string
                    'all'.
    --no-cache      Prevents Docker using cached layers during the build.
    REGISTRY        The url of the registry used for the operation.

decking cluster operations:
    CLUSTER         The cluster as defined in the decking definition file
                    to perform the command on.
    OPERATION       create - Builds containers for a given cluster as well
                        as any implicit or explicit dependencies. Optionally
                        uses group-level overrides if specified by the cluster
                        definition. This method is safe to run multiple times;
                        it will only create the containers in the cluster which
                        don't already exist.
                    start - Starts all the containers in a given cluster. Safe
                        to run multiple times; it will only start containers
                        which aren't already running. Ensures that any
                        dependencies are always started before their dependent
                        services.
                    stop - Stops all the containers in a given cluster. Safe
                        to run multiple times; it will only stop containers
                        which are currently running.
                    restart - Restarts the containers in a given cluster.
                        As with start, all dependencies are restarted in the
                        correct order.
                    status - Provides a quick overview of the status of each
                        container in a cluster. Also displays each container's
                        IP and port mapping information if it is currently
                        running.
                    attach - Attaches to the stdout and stderr streams of each
                        container in a cluster. This is incredibly useful for
                        gaining an insight into the overall cohesion of a
                        cluster and provides a coordinated output log.
                        Survives brief outages in container availability
                        meaning it does not have to be re run each time a
                        container is restarted.
                    build - build the images associated to the cluster.
                    run - Create and start the containers for a given cluster.

Global options:
    --allow-insecure
                    Allow pulling/pushing from/to registries using http, not
                    only https.

    --config=CONFIG Define the file to read the decking definition
                    from. JSON and YAML formats are supported.
                    [default: decking.json]

    --debug         Enable debugging information.

For more detailed help about the format of the decking definition file
and operation please refer to http://decking.io/
"""

from __future__ import print_function

import os
import sys
import yaml
from docopt import docopt, DocoptExit

from decking.runner import Decking
from decking.terminal import Terminal
from decking.schema import ConfigValidator, schema


def _validate_config(config_data):
    validator = ConfigValidator()
    if not validator.validate(config_data, schema):
        raise ValueError(str(validator.errors))


def _read_config(filename):
    try:
        with open(filename) as f:
            config_data = yaml.load(f)
            _validate_config(config_data)
            return config_data
    except IOError:
        # FIXME: why do we obliterate the message of the original exception?
        raise IOError("Could not open cluster configuration file {}".format(
            filename))


def _not_implemented(*args, **kwargs):
    raise NotImplementedError(
        "This operation hasn't been implemented yet")


def main():
    try:
        opts = docopt(__doc__)
    except DocoptExit as error:
        return error.message

    if opts["help"]:
        print(__doc__)
        return 0

    terminal = Terminal()

    try:
        config_filename = os.path.expanduser(opts['--config'])
        base_path = os.path.dirname(config_filename)
        runner = Decking(_read_config(config_filename), base_path)
        commands = {
            'create': runner.create,
            'start': runner.start,
            'run': runner.run,
            'stop': runner.stop,
            'remove': runner.remove,
            'restart': runner.restart,
            'status': runner.status,
            'attach': runner.attach,
        }

        if opts['build']:
            runner.build(opts['WHAT'])
        elif opts['pull'] or opts['push']:
            image = opts['WHAT']
            registry = opts.get('REGISTRY')
            if opts['push']:
                runner.push_thing(image, registry, opts['--allow-insecure'])
            elif opts['pull']:
                runner.pull_thing(image, registry, opts['--allow-insecure'])
        else:
            command, cluster = opts['OPERATION'], opts['CLUSTER']
            if command in commands:
                commands[command](cluster)
            else:
                raise ValueError(
                    "Operation {!r} not supported".format(command))

    except KeyboardInterrupt:
        terminal.print_error("Operation interrupted by user")
        return 1
    except Exception as error:
        if opts["--debug"]:
            raise
        else:
            terminal.print_error("Operation failed", str(error))
            return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())

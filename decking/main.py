"""
Usage:
    decking help
    decking build WHAT [--no-cache] [--config=CONFIG] [--debug]
    decking (push | pull) WHAT [REGISTRY] [--config=CONFIG] [--debug]
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
from decking.runner import Decking
from decking.terminal import Terminal
import yaml
import docker
from docopt import docopt, DocoptExit
from cerberus import Validator

def _read_config(opts):
    schema = {
        'images': {
            'type': 'dict',
            'keyschema': {
                'type': 'string'
            }
        },
        'clusters': {
            'type': 'dict',
            'keyschema': {
                'type': 'list',
                'schema': {'type': 'string'}
# FIXME add support for more complex grouping functionality
#                'schema': {
#                    'group': {
#                        'type': 'string'
#                    },
#                    'containers': {
#                        'type': 'list',
#                        'schema': {
#                            'type': 'string'
#                        }
#                    }
#                }
            }
        },
        'containers': {
            'type': 'dict',
            'required': True,
            'keyschema': {
                'type': 'dict',
                'schema': {
                    'image': {
                        'type': 'string',
                        'required': True
                    },
                    'port': {
                        'type': 'list',
                        'schema': {'type': 'string'}
                    },
                    'env': {
                        'type': 'list',
                        'schema': {'type': 'string'}
                    },
                    'dependencies': {
                        'type': 'list',
                        'schema': {'type': 'string'}
                    },
                    'mount': {
                        'type': 'list',
                        'schema': {'type': 'string'}
                    },
                    'net': {
                        'type': 'string'
                    },
                    'privileged': {
                        'type': 'boolean',
                    }
                }
            }
        },
# FIXME: Add support for grouping behaviours
#        'groups': {
#            'type': 'dict',
#            'keyschema': {
#                'options': {
#                    'port': {
#                        'type': 'list',
#                        'schema': {'type': 'string'}
#                    },
#                    'env': {
#                        'type': 'list',
#                        'schema': {'type': 'string'}
#                    },
#                    'dependencies': {
#                        'type': 'list',
#                        'schema': {'type': 'string'}
#                    },
#                    'mount': {
#                        'type': 'list',
#                        'schema': {'type': 'string'}
#                    }
#                },
#                'containers': {
#                    'type': 'dict',
#                    'keyschema': {
#                        'port': {
#                            'type': 'list',
#                            'schema': {'type': 'string'}
#                        },
#                        'env': {
#                            'type': 'list',
#                            'schema': {'type': 'string'}
#                        },
#                        'dependencies': {
#                            'type': 'list',
#                            'schema': {'type': 'string'}
#                        },
#                        'mount': {
#                            'type': 'list',
#                            'schema': {'type': 'string'}
#                        }
#                    }
#                }
#            }
#        }
    }

    filename = os.path.expanduser(opts["--config"])
    try:
        with open(filename) as f:
            result = yaml.load(f)
            validator = Validator()
            if not validator.validate(result, schema):
                raise ValueError(str(validator.errors))
            return result
    except IOError:
        raise IOError(
            "Could not open cluster configuration file " +
            filename
        )


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
        docker_client = docker.Client(
            base_url=os.environ.get('DOCKER_HOST'),
            version='1.10', timeout=30)
        runner = Decking(_read_config(opts), docker_client, terminal)
        commands = {
            'create': runner.create_cluster,
            'start': runner.start_cluster,
            'run': runner.run_cluster,
            'stop': runner.stop_cluster,
            'remove': runner.remove_cluster,
            'restart': runner.restart_cluster,
            'status': runner.status_cluster,
            'attach': runner.attach_cluster,
        }

        if opts['build']:
            runner.build(opts['WHAT'])
        elif opts['pull'] or opts['push']:
            image = opts['WHAT']
            registry = opts.get('REGISTRY')
            if opts['push']:
                runner.push_thing(image, registry)
            elif opts['pull']:
                runner.pull_thing(image, registry)
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

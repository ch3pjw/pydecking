"""
Usage:
    decking help
    decking pull [REGISTRY] [--config=CONFIG]
    decking push REGISTRY [--config=CONFIG]
    decking build IMAGE [--config=CONFIG] [--no-cache]
    decking OPERATION CLUSTER [--config=CONFIG]

Image build parameter:
    IMAGE           The image name found in the decking definition file.
                    When provided with the literal string 'all', this simply
                    iterates through each key of the images object and builds
                    them in turn.

    --no-cache      Prevents Docker using cached layers during the build.
Cluster operations:
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

Global options:
    --config=CONFIG Define the file to read the decking definition
                    from. JSON and YAML formats are supported.
                    [default: decking.json]

For more detailed help about the format of the decking definition file
and operation please refer to http://decking.io/
"""

from __future__ import print_function

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

    filename = opts["--config"]
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


def main():
    try:
        opts = docopt(__doc__)
    except DocoptExit as error:
        sys.exit(error.message)

    if opts["help"]:
        print(__doc__)
        sys.exit(0)

    terminal = Terminal()

    try:
        docker_client = docker.Client(
            base_url='unix://var/run/docker.sock', version='1.10', timeout=10)
        runner = Decking(_read_config(opts), docker_client)
        commands = {
            'create': runner.create_cluster,
            'start': runner.start_cluster
        }

        if opts['build']:
            runner.build(opts['IMAGE'])
        elif opts["pull"]:
            runner.pull(opts.get('REGISTRY'))
        elif opts['push']:
            runner.push(opts['REGISTRY'])
        else:
            command, cluster = opts['OPERATION'], opts['CLUSTER']
            if command in commands:
                commands[command](cluster)
            else:
                raise NotImplementedError(
                    "This operation hasn't been implemented yet")

    except KeyboardInterrupt:
        terminal.print_error("Operation interrupted by user")
    except NotImplementedError as error:
        terminal.print_error(
            "Operation failed",
            error)


if __name__ == '__main__':
    main()

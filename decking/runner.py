
from __future__ import print_function
import time


class DeckingRunner(object):
    '''Takes decking configuration, as defined in the decking project and
    runs it using the python docker API.

    :parameter decking_config: Python structure containing the parsed
        decking.json file config

    All extra kwargs are passed to the docker python client.
    '''
    def __init__(self, decking_config, docker_client):
        self.decking_config = decking_config
        self.client = docker_client

    @staticmethod
    def _build_volume_binding(mount_spec):
        mount_point, source = mount_spec.split(':', 2)
        return mount_point, {'bind': source, 'ro': False}

    @staticmethod
    def _uncolon_mapping(mapping_as_sequence):
        return dict(item.split(':') for item in mapping_as_sequence)

    def _containter_names_by_dependency(self, container_specs):
        to_process = set(container_specs.keys())
        processed = set()
        while to_process:
            pending = set()
            for name in list(to_process):
                dependencies = container_specs[name].get('dependencies', [])
                links = self._uncolon_mapping(dependencies)
                if all(link in processed for link in links):
                    to_process.remove(name)
                    pending.add(name)
                    yield name
            if pending:
                yield None
            else:
                # Stuck not able to process any more containers
                raise RuntimeError('Arg, you have bad dependencies')
            processed |= pending

    def create_container(self, container_spec, name):
        image = container_spec['image']
        environment = container_spec.get('env', [])
        port_bindings = self._uncolon_mapping(container_spec.get('port', []))
        print('creating container {!r}... '.format(name), end='')
        container_info = self.client.create_container(
            image,
            name=name,
            environment=environment,
            ports=port_bindings.keys())
        print('({})'.format(container_info['Id'][:12]))
        # FIXME: make this less side-effecty?
        container_spec['instance'] = container_info
        return container_info

    def run_container(self, container_spec, name):
        dependencies = container_spec.get('dependencies', [])
        links = self._uncolon_mapping(dependencies)
        volume_bindings = dict(
            self._build_volume_binding(mount_entry)
            for mount_entry in container_spec.get('mount', []))
        port_bindings = self._uncolon_mapping(container_spec.get('port', []))
        if 'instance' not in container_spec:
            raise RuntimeError(
                'Must create a container instance before attempting to run')
        print('running container {!r} ({})...'.format(
            name, container_spec['instance']['Id'][:12]))
        self.client.start(
            container_spec['instance'],
            binds=volume_bindings,
            links=links,
            port_bindings=port_bindings)

    def create_all(self):
        container_specs = self.decking_config['containers']
        created = []
        for name in self._containter_names_by_dependency(container_specs):
            if name:
                container_spec = container_specs[name]
                self.create_container(container_spec, name)
                created.append(name)
        return created

    def run_all(self):
        container_specs = self.decking_config['containers']
        running = []
        for name in self._containter_names_by_dependency(container_specs):
            if name:
                container_spec = container_specs[name]
                self.run_container(container_spec, name)
                running.append(name)
            else:
                # FIXME: make some way to tell if container is alive
                time.sleep(6)
        return running




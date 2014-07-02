from __future__ import print_function
import os
import time
import json
from copy import deepcopy


class DeckingRunner(object):
    '''Takes decking configuration, as defined in the decking project and
    runs it using the python docker API.

    :parameter decking_config: Python structure containing the parsed
        decking.json file config

    All extra kwargs are passed to the docker python client.
    '''
    def __init__(self, decking_config, docker_client):
        self.image_specs = self._parse_image_specs(
            decking_config.get('images', {}))
        self.container_specs = self._parse_container_specs(
            decking_config['containers'])
        self.cluster_specs = decking_config['clusters']
        self.client = docker_client

    def _parse_image_specs(self, image_specs):
        '''Translates the image specifications in the decking.json file into an
        internal representation that has more detail
        '''
        result = {}
        for tag, path in image_specs.items():
            result[tag] = {'path': path}
            with open(os.path.join(path, 'Dockerfile')) as f:
                dependency = self._parse_dockerfile(f)
            if dependency in image_specs:
                dependencies = [dependency]
            else:
                # Ignore external dependencies
                dependencies = []
            result[tag]['dependencies'] = dependencies
        return result

    @staticmethod
    def _parse_dockerfile(docker_file):
        for line in docker_file:
            if line.upper().startswith('FROM'):
                return line.split(None, 1)[1].strip()

    def _parse_container_specs(self, container_specs):
        '''Translates the container specifications in the decking.json file
        into an internal representation that has more detail.
        '''
        result = {}
        for name, spec in container_specs.items():
            result[name] = deepcopy(spec)
            links = self._uncolon_mapping(spec.get('dependencies', []))
            result[name]['links'] = links
            result[name]['dependencies'] = list(links.keys())
        return result

    @staticmethod
    def _build_volume_binding(mount_spec):
        mount_point, source = mount_spec.split(':', 2)
        return mount_point, {'bind': source, 'ro': False}

    @staticmethod
    def _uncolon_mapping(mapping_as_sequence):
        return dict(item.split(':') for item in mapping_as_sequence)

    def build_image(self, tag, image_spec):
        print('building image {!r}...'.format(tag))
        stream = self.client.build(image_spec['path'], tag=tag)
        for line in stream:
            line = json.loads(line)
            print(line['stream'].strip())

    def _names_by_dependency(self, specs):
        to_process = set(specs.keys())
        processed = set()
        while to_process:
            pending = set()
            for name in list(to_process):
                dependencies = specs[name].get('dependencies', [])
                if all(dep in processed for dep in dependencies):
                    to_process.remove(name)
                    pending.add(name)
                    yield name
            if pending:
                yield None
            else:
                # Stuck not able to process any more containers
                raise RuntimeError('Arg, you have bad dependencies')
            processed |= pending

    def create_container(self, name, container_spec):
        image = container_spec['image']
        environment = container_spec.get('env', [])
        port_bindings = self._uncolon_mapping(container_spec.get('port', []))
        print('creating container {!r}... '
              ''.format(name), end='')
        container_info = self.client.create_container(
            image,
            name=name,
            environment=environment,
            ports=port_bindings.keys())
        print('({})'.format(container_info['Id'][:12]))
        # FIXME: make this less side-effecty?
        container_spec['instance'] = container_info
        return container_info

    def run_container(self, name, container_spec):
        links = container_spec.get('links', [])
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

    def _dependency_aware_map(self, func, iterable, else_=lambda: None):
        processed = []
        for key in self._names_by_dependency(iterable):
            if key:
                item = iterable[key]
                func(key, item)
                processed.append(key)
            else:
                else_()
        return processed

    def build(self, image):
        if image != 'all':
            raise ValueError('You can only build all images right now')
        return self._dependency_aware_map(self.build_image, self.image_specs)

    @staticmethod
    def _filter_dict_by_keys(d, keys):
        return dict(filter(lambda item: item[0] in keys, d.items()))

    def _cluster_and_dependency_aware_map(
            self, cluster, func, container_specs, *args, **kwargs):
        if cluster not in self.cluster_specs:
            raise ValueError(
                'Undefined cluster name {!r}. Defined: {!r}'.format(
                    cluster, ', '.join(self.cluster_specs.keys())))
        container_names = self.cluster_specs[cluster]
        container_specs = self._filter_dict_by_keys(
            container_specs, container_names)
        return self._dependency_aware_map(
            func, container_specs, *args, **kwargs)

    def create(self, cluster):
        return self._cluster_and_dependency_aware_map(
            cluster, self.create_container, self.container_specs)

    def start(self, cluster):
        containers = self.client.containers(all=True, limit=-1)
        for container_info in containers:
            for name in container_info['Names']:
                # strip off the leading /
                name = name[1:]
                if name in self.container_specs:
                    self.container_specs[name]['instance'] = container_info
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.run_container,
            self.container_specs,
            else_=lambda: time.sleep(6))

    def pull(self, registry=None):
        for container_spec in self.container_specs.values():
            remote_image = image = container_spec['image']
            if registry:
                remote_image = '{}/{}'.format(registry, image)

            self.client.pull(remote_image)
            if remote_image != image:
                self.client.tag(remote_image, image)
                self.client.remove_image(remote_image)


from __future__ import print_function
import os
import time
import json
from functools import partial
from copy import deepcopy


class Decking(object):
    '''Takes decking configuration, as defined in the decking project and
    runs it using the python docker API.

    :parameter decking_config: Python structure containing the parsed
        decking.json file config

    All extra kwargs are passed to the docker python client.
    '''

    def __init__(self, decking_config, docker_client, terminal):
        self._raw_image_specs = decking_config.get('images', {})
        self._image_specs = None
        self.container_specs = self._parse_container_specs(
            decking_config['containers'])
        self.cluster_specs = decking_config['clusters']
        self.client = docker_client
        self._term = terminal


    @property
    def image_specs(self):
        '''We lazily call parsing of the image_specs, as it goes away and tries
        to load the referenced Dockerfiles. We might not want to do this should
        we not be doing anything with images on our machine.
        '''
        # FIXME: potentially we don't need to worry about this - if someone has
        # specified paths to Dockerfiles it might makes sense just to die if
        # the paths are wrong?
        if self._image_specs is None:
            self._image_specs = self._parse_image_specs(self._raw_image_specs)
        return self._image_specs

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
        self._term.print_step('building image {!r}...'.format(tag))
        stream = self.client.build(image_spec['path'], tag=tag, rm=True)
        for steam_element in stream:
            steam_element = json.loads(steam_element)
            if 'stream' in steam_element:
                for line in steam_element['stream'].strip().splitlines():
                    self._term.print_line(line)

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
        self._term.print_step(
            'creating container {!r}... '.format(name))
        container_info = self.client.create_container(
            image,
            name=name,
            environment=environment,
            ports=port_bindings.keys())
        self._term.print_line('({})'.format(container_info['Id'][:12]))
        # FIXME: make this less side-effecty?
        container_spec['instance'] = container_info
        return container_info

    def start_container(self, name, container_spec):
        links = container_spec.get('links', [])
        volume_bindings = dict(
            self._build_volume_binding(mount_entry)
            for mount_entry in container_spec.get('mount', []))
        port_bindings = self._uncolon_mapping(container_spec.get('port', []))
        if 'instance' not in container_spec:
            raise RuntimeError(
                'Must create a container instance before attempting to run')
        self._term.print_step('starting container {!r} ({})...'.format(
            name, container_spec['instance']['Id'][:12]))
        self.client.start(
            container_spec['instance'],
            binds=volume_bindings,
            links=links,
            port_bindings=port_bindings,
            # FIXME: take some time to consider the name of this option
            network_mode=container_spec.get('net'),
        )

    def pull_container(self, name, container_spec, registry=None):
        self.pull_single_image(container_spec['image'], registry)

    def pull_single_image(self, image, registry=None):
        remote_image = image
        if registry:
            remote_image = '{}/{}'.format(registry, image)

        self._term.print_step('pulling image {}...'.format(remote_image))
        response = self.client.pull(remote_image)
        for line in response.splitlines():
            try:
                line = json.loads(line)
            except ValueError:
                # The output format from this client command is a bit
                # rubbish... just ignore parsing errors if we can't help
                pass
            else:
                if 'errorDetail' in line:
                    self._term.print_error(line['errorDetail']['message'])
        if remote_image != image:
            self.client.tag(remote_image, image)
            self.client.remove_image(remote_image)

    def push_container(self, name, container_spec, registry):
        self.push_single_image(container_spec['image'], registry)

    def push_single_image(self, image, registry):
        remote_image = '{}/{}'.format(registry, image)
        self.client.tag(image, remote_image)
        self._term.print_step('pushing image {}...'.format(remote_image))
        self.client.push(remote_image)
        self.client.remove_image(remote_image)

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
            raise NotImplementedError('You can only build all images right now')
        return self._dependency_aware_map(self.build_image, self.image_specs)

    def _push_or_pull_thing(self, thing, registry,
                            image_operation, cluster_operation):
        # FIXME: We probably don't want to use _raw_image_specs; but we want to
        # avoid trying to read Dockerfiles for this action
        if thing == 'all':
            matched_images = self._raw_image_specs.keys()
        else:
            if thing in self._raw_image_specs:
                matched_images = [thing]
            else:
                matched_images = []

        if matched_images:
            for img in matched_images:
                image_operation(img, registry)
        else:
            try:
                cluster_operation(thing, registry)
            except ValueError as no_cluster:
                raise ValueError(
                    'Undefined image name {!r}. Defined: {!r}\n{}'.format(
                        thing,
                        self._raw_image_specs.keys(),
                        no_cluster.message)
                )

    def pull_thing(self, thing, registry=None):
        self._push_or_pull_thing(
            thing, registry, self.pull_single_image, self.pull_cluster)

    def push_thing(self, thing, registry):
        self._push_or_pull_thing(
            thing, registry, self.push_single_image, self.push_cluster)

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

    def create_cluster(self, cluster):
        return self._cluster_and_dependency_aware_map(
            cluster, self.create_container, self.container_specs)

    def start_cluster(self, cluster):
        containers = self.client.containers(all=True, limit=-1)
        for container_info in containers:
            for name in container_info['Names']:
                # strip off the leading /
                name = name[1:]
                if name in self.container_specs:
                    self.container_specs[name]['instance'] = container_info
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.start_container,
            self.container_specs,
            else_=lambda: time.sleep(6))

    def pull_cluster(self, cluster, registry=None):
        return self._cluster_and_dependency_aware_map(
            cluster,
            partial(self.pull_container, registry=registry),
            self.container_specs)

    def push_cluster(self, cluster, registry):
        return self._cluster_and_dependency_aware_map(
            cluster,
            partial(self.push_container, registry=registry),
            self.container_specs)

from __future__ import print_function
try:
    from queue import Queue
except ImportError:
    from Queue import Queue
import threading
import sys
import signal
import docker
import os
import time
import json
from functools import partial
from copy import deepcopy
from collections import Sequence


class Decking(object):
    '''Takes decking configuration, as defined in the decking project and
    runs it using the python docker API.

    :parameter decking_config: Python structure containing the parsed
        decking.json file config

    All extra kwargs are passed to the docker python client.
    '''

    def __init__(
            self, decking_config, docker_client, terminal, base_path=''):
        self._raw_image_specs = decking_config.get('images', {})
        self._image_specs = None
        # Used as base path from which to find Dockerfiles:
        self._base_path = base_path
        self.container_specs = self._parse_container_specs(
            decking_config['containers'])
        self.cluster_specs = decking_config['clusters']
        self.group_specs = decking_config.get('groups', {})
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
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(self._base_path, path))
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

    def _consume_stream(self, stream):
        for item in stream:
            item = json.loads(item)
            if 'stream' in item:
                for line in item['stream'].strip().splitlines():
                    self._term.print_line(line)
            elif 'status' in item:
                # TODO: report progress
                pass
            elif 'error' in item:
                raise RuntimeError(item['error'])

    def build_image(self, tag, image_spec):
        self._term.print_step('building image {!r}...'.format(tag))
        stream = self.client.build(image_spec['path'], tag=tag, rm=True)
        self._consume_stream(stream)

    def create_container(self, name, container_spec):
        if 'instance' in container_spec:
            self._term.print_step("{} is already created ({})".format(
                name,
                container_spec['instance']['Id'][:12]))
            return self.client.inspect_container(name)

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
            self._term.print_error("container {!r} isn't created".format(name))
            raise RuntimeError(
                'Must create a container instance before attempting to run')
        self._term.print_step('starting container {!r} ({})...'.format(
            name, container_spec['instance']['Id'][:12]))
        self.client.start(
            container_spec['instance'],
            binds=volume_bindings,
            links=links,
            port_bindings=port_bindings,
            privileged=container_spec.get('privileged', False),
            # FIXME: take some time to consider the name of this option
            network_mode=container_spec.get('net'),
        )

    def run_container(self, name, container_spec):
        self.create_container(name, container_spec)
        self.start_container(name, container_spec)

    def stop_container(self, name, container_spec):
        if 'instance' in container_spec:
            self._term.print_step('stopping container {!r} ({})...'.format(
                name, container_spec['instance']['Id'][:12]))
            # Timeout must be smaller than our client's socket read timeout:
            self.client.stop(container_spec['instance'], timeout=8)

    def status_container(self, name, container_spec):
        if 'instance' in container_spec:
            status_string = '{!r} ({}): {}'.format(
                name,
                container_spec['instance']['Id'][:12],
                container_spec['instance']['Status']
            )
            if container_spec['instance']['Status'].startswith('Up'):
                self._term.print_step(status_string)
            else:
                self._term.print_warning(status_string)
            for port in container_spec['instance']['Ports']:
                if 'IP' in port:
                    self._term.print_line('{} {} [{}=>{}]'.format(
                        port['Type'],
                        port['IP'],
                        port['PrivatePort'],
                        port['PublicPort'])
                    )
                else:
                    self._term.print_line('{} [{}]'.format(
                        port['Type'],
                        port['PrivatePort'])
                    )
        else:
            self._term.print_step("{!r} isn't created".format(name))

    def remove_container(self, name, container_spec):
        if 'instance' in container_spec:
            self._term.print_step('removing container {!r} ({})...'.format(
                name, container_spec['instance']['Id'][:12]))
            try:
                self.client.remove_container(container_spec['instance'])
            except docker.errors.APIError as error:
                self._term.print_error(
                    "couldn't remove container {!r} ({})".format(
                        name, container_spec['instance']['Id'][:12]
                    ),
                    str(error)
                )
        else:
            self._term.print_warning('no instance found for {!r}'.format(name))

    def pull_container(self, name, container_spec, registry=None,
                       allow_insecure=False):
        self.pull_single_image(
            container_spec['image'], registry, allow_insecure)

    def pull_single_image(self, image, registry=None, allow_insecure=False):
        remote_image = image
        if registry:
            remote_image = '{}/{}'.format(registry, image)

        self._term.print_step('pulling image {}...'.format(remote_image))
        stream = self.client.pull(
            remote_image,
            insecure_registry=allow_insecure,
            stream=True)
        self._consume_stream(stream)

        if remote_image != image:
            self.client.tag(remote_image, image)
            self.client.remove_image(remote_image)

    def push_container(self, name, container_spec, registry,
                       allow_insecure=False):
        self.push_single_image(
            container_spec['image'], registry, allow_insecure)

    def push_single_image(self, image, registry, allow_insecure=False):
        remote_image = '{}/{}'.format(registry, image)
        self.client.tag(image, remote_image)
        self._term.print_step('pushing image {}...'.format(remote_image))
        stream = self.client.push(
            remote_image,
            insecure_registry=allow_insecure,
            stream=True)
        self._consume_stream(stream)
        self.client.remove_image(remote_image)

    def build(self, image):
        if image != 'all':
            raise NotImplementedError(
                'You can only build all images right now')
        return self._dependency_aware_map(self.build_image, self.image_specs)

    def _push_or_pull_thing(self, thing, registry, allow_insecure,
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
                image_operation(img, registry, allow_insecure)
        else:
            try:
                cluster_operation(thing, registry, allow_insecure)
            except ValueError as no_cluster:
                raise ValueError(
                    'Undefined image name {!r}. Defined: {!r}\n{}'.format(
                        thing,
                        self._raw_image_specs.keys(),
                        no_cluster.message)
                )

    def pull_thing(self, thing, registry=None, allow_insecure=False):
        self._push_or_pull_thing(
            thing, registry, allow_insecure, self.pull_single_image,
            self.pull_cluster)

    def push_thing(self, thing, registry, allow_insecure=False):
        self._push_or_pull_thing(
            thing, registry, allow_insecure, self.push_single_image,
            self.push_cluster)

    @staticmethod
    def _filter_dict_by_keys(d, keys):
        return dict(filter(lambda item: item[0] in keys, d.items()))

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

    def _dependency_aware_map(
            self, func, iterable, reverse=False, else_=lambda: None):
        processed = []
        iterator = self._names_by_dependency(iterable)
        if reverse:
            iterator = reversed(tuple(iterator))
        for key in iterator:
            if key:
                item = iterable[key]
                func(key, item)
                processed.append(key)
            else:
                else_()
        return processed

    def _cluster_and_dependency_aware_map(
            self, cluster_name, func, container_specs, group_specs, **kwargs):
        if cluster_name not in self.cluster_specs:
            raise ValueError(
                'Undefined cluster name {!r}. Defined: {!r}'.format(
                    cluster_name, ', '.join(self.cluster_specs.keys())))
        container_specs = self._build_dynamic_container_specs_for_cluster(
            self.cluster_specs[cluster_name], container_specs, group_specs)
        return self._dependency_aware_map(func, container_specs, **kwargs)

    def _build_dynamic_container_specs_for_cluster(
            self, cluster_spec, container_specs, group_specs):
        '''A cluster spec can be a simple list of container names or a dict of
        "group" and "containers", unfortunately. Furthermore, when a group is
        specified, that modifies the specifications of the containers in the
        cluster.

        :returns dict: A dict specifying all the containers in the cluster
        '''
        # FIXME: It might be prudent to turn images, containers, clusters and
        # groups into full-blown objects, to better manage cross references and
        # stop us having to make inferences about data all over the place.
        if isinstance(cluster_spec, Sequence):
            container_names = cluster_spec
            group_spec = {'options': {}, 'containers': {}}
        else:
            container_names = cluster_spec['containers']
            group_spec = group_specs[cluster_spec['group']]
        container_specs = self._filter_dict_by_keys(
            container_specs, container_names)
        for name, spec in container_specs.items():
            spec.update(group_spec['options'])
            container_specific_update = group_spec['containers'].get(name, {})
            spec.update(container_specific_update)
        return container_specs

    def create_cluster(self, cluster):
        self._populate_live_container_data()
        return self._cluster_and_dependency_aware_map(
            cluster, self.create_container, self.container_specs,
            self.group_specs)

    def _populate_live_container_data(self):
        containers = self.client.containers(all=True, limit=-1)
        for container_info in containers:
            for name in container_info['Names']:
                # strip off the leading /
                name = name[1:]
                if name in self.container_specs:
                    self.container_specs[name]['instance'] = container_info

    def start_cluster(self, cluster):
        self._populate_live_container_data()
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.start_container,
            self.container_specs,
            self.group_specs)

    def run_cluster(self, cluster):
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.run_container,
            self.container_specs,
            self.group_specs)

    def stop_cluster(self, cluster):
        self._populate_live_container_data()
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.stop_container,
            self.container_specs,
            self.group_specs,
            reverse=True)

    def restart_cluster(self, cluster):
        self.stop_cluster(cluster)
        return self.start_cluster(cluster)

    def remove_cluster(self, cluster):
        self._populate_live_container_data()
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.remove_container,
            self.container_specs,
            self.group_specs)

    def pull_cluster(self, cluster, registry=None, allow_insecure=False):
        return self._cluster_and_dependency_aware_map(
            cluster,
            partial(self.pull_container,
                    registry=registry,
                    allow_insecure=allow_insecure),
            self.container_specs,
            self.group_specs)

    def push_cluster(self, cluster, registry):
        return self._cluster_and_dependency_aware_map(
            cluster,
            partial(self.push_container, registry=registry),
            self.container_specs,
            self.group_specs)

    def status_cluster(self, cluster):
        self._populate_live_container_data()
        return self._cluster_and_dependency_aware_map(
            cluster,
            self.status_container,
            self.container_specs,
            self.group_specs)

    @staticmethod
    def _log_consumer(container, stream, queue):
        for line in stream:
            queue.put((container, line))

    def _display_logs(self, log_queue):
        current_container = (None, None)

        while True:
            container, line = log_queue.get()
            if container != current_container:
                current_container = container
                self._term.print_step(container)
            self._term.print_line(line.strip())
            time.sleep(0.1)

    @staticmethod
    def _quit(signal, frame):
        sys.exit(0)

    def attach_cluster(self, cluster):
        self._populate_live_container_data()
        threads = []

        log_queue = Queue()

        signal.signal(signal.SIGINT, self._quit)

        for name in self.cluster_specs[cluster]:
            stdout_stream = self.client.attach(name, stream=True)
            thread = threading.Thread(
                target=self._log_consumer,
                args=(name, stdout_stream, log_queue)
            )
            thread.daemon = True
            threads.append(thread)
            thread.start()

        thread = threading.Thread(
            target=self._display_logs,
            args=(log_queue,)
        )
        thread.daemon = True
        threads.append(thread)
        thread.start()

        signal.pause()

from functools import wraps
import docker
import threading
try:
    from queue import Queue
except ImportError:
    from Queue import Queue

from decking.terminal import term
from decking.util import consume_stream, iter_dependencies

END_OF_STREAM = object()


class Named(object):
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<{} {!r}>'.format(self.__class__.__name__, self.name)


class Image(Named):
    def __init__(self, docker_client, name, path):
        super(Image, self).__init__(name)
        self._docker_client = docker_client
        self.path = path
        self._dependencies = None

    @property
    def dependencies(self):
        if self._dependencies is None:
            self._dependencies = self._parse_dockerfile(self.path)
        return self._dependencies

    @staticmethod
    def _parse_dockerfile(path):
        '''Parses this Image's Dockerfile in order to return any dependency
        on another image it may have.
        '''
        with open(path) as docker_file:
            for line in docker_file:
                if line.upper().startswith('FROM'):
                    dependency = line.split(None, 1)[1].strip()
                    return [dependency]
            else:
                return []

    def build(self):
        term.print_step('building image {!r}...'.format(self.name))
        stream = self._docker_client.build(self.path, tag=self.name, rm=True)
        consume_stream(stream)

    def push(self, registry, allow_insecure=False):
        remote_image_name = '{}/{}'.format(registry, self.name)
        self._docker_client.tag(self.name, remote_image_name)
        term.print_step('pushing image {}...'.format(remote_image_name))
        stream = self._docker_client.push(
            remote_image_name,
            insecure_registry=allow_insecure,
            stream=True)
        consume_stream(stream)
        self._docker_client.remove_image(remote_image_name)

    def pull(self, registry=None, allow_insecure=False):
        if registry:
            remote_image_name = '{}/{}'.format(registry, self.name)
        else:
            remote_image_name = self.name

        term.print_step('pulling image {}...'.format(remote_image_name))
        stream = self._docker_client.pull(
            remote_image_name,
            insecure_registry=allow_insecure,
            stream=True)
        consume_stream(stream)

        if remote_image_name != self.name:
            self._docker_client.tag(remote_image_name, self.name)
            self._docker_client.remove_image(remote_image_name)


class ContainerData(Named):
    '''Encapsulates the configuration data for a container, but not any dynamic
    functionality. We use this because :class:`Group`s refer to container
    configuration, but don't actually define runable containers, and we want a
    consistent base abstraction.
    '''
    def __init__(
            self, name, image=None, port_bindings=None, environment=None,
            net=None, privileged=False, volume_bindings=None):
        super(ContainerData, self).__init__(name)
        self.image = image
        self.port_bindings = port_bindings or {}
        self.environment = environment or {}
        self.net = net
        self.privileged = privileged
        self.volume_bindings = volume_bindings or {}


def assert_created(method):
    @wraps(method)
    def wrapped_method(self, *args, **kwargs):
        if not self.created:
            raise RuntimeError("Docker container {!r} not created!".format(
                self.name))
        return method(self, *args, **kwargs)
    return wrapped_method


class Container(ContainerData):
    def __init__(
            self, docker_client, name, image, dependencies=None, **kwargs):
        '''
        :parameter dependencies: list of other Container objects defining the
            containers upon which the container defined in this object depends
            to run.
        '''
        super(Container, self).__init__(name, image, **kwargs)
        self.dependencies = dependencies or {}
        self._docker_client = docker_client
        self._docker_container_info = None

    @property
    def created(self):
        return bool(self._docker_container_info)

    @property
    @assert_created
    def id(self):
        return self._docker_container_info['Id'][:12]

    def _get_group_modified_dict_attribute(self, group, attr_name):
        value = dict(getattr(self, attr_name))
        if group:
            value.update(getattr(group.options, attr_name))
            for name, container in group.per_container_specs.items():
                if name == self.name:
                    value.update(getattr(container, attr_name))
        return value

    def create(self, group=None):
        if self.created:
            term.print_step('{!r} is already created ({})'.format(
                self.name, self.id))
        else:
            term.print_step('creating container {!r}...'.format(self.name))
            environment = self._get_group_modified_dict_attribute(
                group, 'environment')
            self._docker_container_info = self._docker_client.create_container(
                self.image.name,
                name=self.name,
                environment=environment,
                ports=self.port_bindings.keys())
            term.print_line('({})'.format(self.id))

    @staticmethod
    def _format_volume_bindings(volume_bindings):
        return {
            container_path: {'bind': local_path, 'ro': False} for
            container_path, local_path in volume_bindings.items()}

    @assert_created
    def start(self, group=None):
        term.print_step('starting container {!r} ({})...'.format(
            self.name, self.id))
        volume_bindings = self._format_volume_bindings(
            self._get_group_modified_dict_attribute(group, 'volume_bindings'))
        self._docker_client.start(
            self._docker_container_info,
            binds=volume_bindings,
            links={
                container.name: alias for container, alias in
                self.dependencies.items()},
            port_bindings=self.port_bindings,
            privileged=self.privileged,
            network_mode=self.net)

    def run(self, group=None):
        self.create(group)
        self.start(group)

    @assert_created
    def stop(self):
        term.print_step('stopping container {!r} ({})...'.format(
            self.name, self.id))
        # timeout must be smaller than our client's socket read timeout:
        self._docker_client.stop(self._docker_container_info, timeout=8)

    def status(self):
        if self.created:
            status = self._docker_container_info['Status']
            status_string = '{!r} ({}): {}'.format(
                self.name, self.id, status)
            if status.startswith('Up'):
                term.print_step(status_string)
            else:
                term.print_warning(status_string)
            for port in self._docker_container_info['Ports']:
                if 'IP' in port:
                    term.print_line('{} {} [{}=>{}]'.format(
                        port['Type'],
                        port['IP'],
                        port['PrivatePort'],
                        port['PublicPort']))
                else:
                    term.print_line('{} [{}]'.format(
                        port['Type'],
                        port['PrivatePort']))
        else:
            term.print_step("container {!r} isn't created".format(self.name))

    @assert_created
    def remove(self):
        term.print_step('removing container {!r} ({})...'.format(
            self.name, self.id))
        try:
            self._docker_client.remove_container(self._docker_container_info)
        except docker.errors.APIError as error:
            term.print_error("couldn't remove container {!r} ({})".format(
                self.name, self.id), str(error))

    def attach(self, log_queue):
        stdout_stream = self._docker_client.attach(self.name, stream=True)
        thread = threading.Thread(
            target=self._log_consumer, args=(stdout_stream, log_queue))
        thread.daemon = True
        thread.start()
        return thread

    def _log_consumer(self, stream, log_queue):
        for line in stream:
            log_queue.put((self.name, line))
        log_queue.put((self.name, END_OF_STREAM))


class Group(Named):
    def __init__(self, name, options, per_container_specs):
        '''
        :parameter ContainerData: global settings applied to all containers
            with this group.
        :parameter dict per_container_specs: mapping of containers to
            :class:`ConatinerData` instances that provide context-dependent
            overrides of default container specifications for a cluster.
        '''
        super(Group, self).__init__(name)
        self.options = options
        self.per_container_specs = per_container_specs


class Cluster(Named):
    def __init__(self, docker_client, name, containers, group=None):
        super(Cluster, self).__init__(name)
        self._docker_client = docker_client
        self.containers = containers
        self.group = group

    def __iter__(self):
        return iter_dependencies(self.containers, lambda c: c.dependencies)

    def create(self):
        for container in self:
            container.create(self.group)

    def start(self):
        for container in self:
            container.start(self.group)

    def run(self):
        for container in self:
            container.run(self.group)

    def status(self):
        for container in self:
            container.status()

    def stop(self):
        for container in reversed(tuple(self)):
            container.stop()

    def remove(self):
        for container in reversed(tuple(self)):
            container.remove()

    def _display_logs(self, attached, log_queue, term):
        current_container = None, None
        while attached:
            container, line = log_queue.get(timeout=60 * 60)
            if line is END_OF_STREAM:
                attached.remove(container)
                term.print_warning('{}: detached'.format(container))
            else:
                if container != current_container:
                    current_container = container
                    term.print_step(container)
                term.print_line(line.strip())
        term.print_warning('All containers detached')

    def attach(self, term=term):
        attached = set()
        threads = []
        log_queue = Queue()
        for container in self:
            attached.add(container.name)
            threads.append(container.attach(log_queue))
        self._display_logs(attached, log_queue, term)

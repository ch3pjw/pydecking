import docker
import os
from collections import Sequence

from decking.util import undelimit_mapping, iter_dependencies
from decking.components import Image, ContainerData, Container, Cluster, Group


class Decking(object):
    '''Takes validated decking configuration, as defined in the decking
    project, and runs it using the Python docker API.

    :parameter decking_config: Python mapping containing the validated
        decking.json file_config
    '''
    def __init__(self, decking_config, base_path='', docker_client=None):
        self._base_path = base_path
        self.client = docker_client or docker.Client(
            base_url=os.environ.get('DOCKER_HOST'), version='1.10', timeout=30)
        self.images = self._make_images(decking_config['images'])
        self.containers = self._make_containers(decking_config['containers'])
        self.groups = self._make_groups(decking_config.get('groups', {}))
        self.clusters = self._make_clusters(decking_config['clusters'])
        self._populate_live_container_info()

    def _normalise_path(self, path):
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(self._base_path, path))
        return path

    def _make_images(self, config_data):
        image_specs = {}
        for name, path in config_data.items():
            path = os.path.join(self._normalise_path(path), 'Dockerfile')
            image_specs[name] = Image(self.client, name, path)
        return image_specs

    @staticmethod
    def _get_container_config_dependencies(config_data):
        return undelimit_mapping(config_data.get('dependencies', []))

    def _make_containers(self, config_data):
        for name, config in config_data.items():
            deps = self._get_container_config_dependencies(config)
            if not all(d in config_data for d in deps):
                raise ValueError(
                    "'dependencies' for container {!r} references "
                    "undefined container".format(name))

        containers = {}
        for name in iter_dependencies(
                config_data,
                lambda name: self._get_container_config_dependencies(
                    config_data[name])):
            containers[name] = self._make_container(
                name, config_data[name], containers)
        return containers

    def _process_container_config(self, container_config):
        port_bindings = undelimit_mapping(container_config.get('port', []))
        volume_bindings = undelimit_mapping(
            container_config.get('mount', []), reverse_mapping=True)
        volume_bindings = {
            k: self._normalise_path(v) for k, v in volume_bindings.items()}
        environment = undelimit_mapping(container_config.get('env', []), '=')
        return port_bindings, volume_bindings, environment

    def _make_container(self, name, container_config, existing_containers):
        image = self.images[container_config['image']]
        links = undelimit_mapping(container_config.get('dependencies', []))
        dependencies = {
            existing_containers[name]: alias for name, alias in links.items()}
        port_bindings, volume_bindings, environment = (
            self._process_container_config(container_config))
        return Container(
            self.client, name, image, dependencies=dependencies,
            port_bindings=port_bindings, environment=environment,
            net=container_config.get('net'),
            privileged=container_config.get('privileged'),
            volume_bindings=volume_bindings)

    def _make_container_data(self, name, container_config):
        port_bindings, volume_bindings, environment = (
            self._process_container_config(container_config))
        return ContainerData(
            name, port_bindings=port_bindings, environment=environment,
            net=container_config.get('net'),
            privileged=container_config.get('privileged'),
            volume_bindings=volume_bindings)

    def _make_groups(self, config_data):
        groups = {}
        for name, config in config_data.items():
            options = self._make_container_data(
                name + '_options', config.get('options', {}))
            per_container_configs = config.get('containers', {})
            per_container_specs = {}
            for cont_name, cont_config in per_container_configs.items():
                per_container_specs[self.containers[cont_name]] = (
                    self._make_container_data(cont_name, cont_config))
            groups[name] = Group(name, options, per_container_specs)
        return groups

    def _make_clusters(self, config_data):
        clusters = {}
        for name, config in config_data.items():
            if isinstance(config, Sequence):
                containers = [
                    self.containers[cont_name] for cont_name in config]
                group_name = None
            else:
                containers = [
                    self.containers[cont_name] for cont_name in
                    config['containers']]
                group_name = config.get('group')
            group = self.groups[group_name] if group_name is not None else None
            clusters[name] = Cluster(self.client, name, containers, group)
        return clusters

    def _populate_live_container_info(self):
        container_infos = self.client.containers(all=True, limit=-1)
        for container_info in container_infos:
            for name in container_info['Names']:
                name = name.lstrip('/')
                if name in self.containers:
                    self.containers[name]._docker_container_info = (
                        container_info)

    def _get_images_by_name(self, name):
        if name == 'all':
            return self.images
        elif name in self.images:
            return {name: self.images[name]}
        elif name in self.clusters:
            return {
                container.image.name: container.image for container in
                self.clusters[name]}
        else:
            raise ValueError("Can't find enity named {!r}".format(name))

    @staticmethod
    def _iter_images_by_dependency(images):
        images_dependency_names = {}
        for name, image in images.items():
            # Remove external dependencies:
            dependencies = filter(lambda n: n in images, image.dependencies)
            images_dependency_names[name] = dependencies
        for image_name in iter_dependencies(
                images, images_dependency_names.__getitem__):
            yield images[image_name]

    def build(self, image_name):
        built = []
        for image in self._iter_images_by_dependency(
                self._get_images_by_name(image_name)):
            image.build()
            built.append(image)
        return built

    def create(self, name):
        return self.clusters[name].create()

    def start(self, name):
        return self.clusters[name].start()

    def run(self, name):
        return self.clusters[name].run()

    def stop(self, name):
        return self.clusters[name].stop()

    def status(self, name):
        return self.clusters[name].status()

    def restart(self, name):
        self.clusters[name].stop()
        self.clusters[name].restart()

    def remove(self, name):
        return self.clusters[name].remove()

    def attach(self, name):
        return self.clusters[name].attach()

    def push(self, name, *args, **kwargs):
        for image in self._get_images_by_name(name):
            image.push(*args, **kwargs)

    def pull(self, name, *args, **kwargs):
        for image in self._get_images_by_name(name):
            image.pull(*args, **kwargs)

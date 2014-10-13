from unittest import TestCase
from mock import Mock, MagicMock, call

import os
import json
import docker

from decking.terminal import Terminal
from decking.components import Image, Container, ContainerData, Group, Cluster

here = os.path.dirname(__file__)


class BaseTest(TestCase):
    def setUp(self):
        self.docker_client = MagicMock(spec=docker.Client)
        self.image = Image(self.docker_client, 'image_name', 'some/path')
        self.dependency = Container(
            self.docker_client, 'dependency_name', self.image)
        self.container = Container(
            self.docker_client, 'container_name', self.image,
            port_bindings={'1111': '2222'}, environment={'moose': 'pants'},
            net='host', privileged=True,
            dependencies={self.dependency: 'dependency_alias'},
            volume_bindings={'/tmp/': '/normalised/local/foo/'})
        self.cluster = Cluster(
            self.docker_client, 'cluster_name',
            [self.container, self.dependency])
        self.group = Group(
            name='fluffy',
            options=ContainerData(
                'unimportant', environment={
                    'moose': 'overridden', 'pants': 'extra'}),
            per_container_specs={
                self.dependency: ContainerData(
                    'never used', environment={'moose': 'llama'}),
                self.container: ContainerData(
                    'never used', environment={'more': 'extra extra'},
                    volume_bindings={'/tmp/': '/normalised/local/bar/'})})


class TestImage(BaseTest):
    def setUp(self):
        super(TestImage, self).setUp()
        self.stream = [
            json.dumps({'stream': 'stream\nof\narbitrary\nwords'})] * 2

    def test_dependencies(self):
        path = os.path.join(here, 'data', 'alice')
        self.image.path = path
        self.assertEqual(self.image.dependencies, ['ubuntu'])

    def test_caching_dependencies(self):
        self.image._parse_dockerfile = lambda path: ['some dep']
        self.assertEqual(self.image.dependencies, ['some dep'])
        self.image._parse_dockerfile = lambda path: ['unread dep']
        self.assertEqual(self.image.dependencies, ['some dep'])

    def test_repr(self):
        self.assertIn('Image', repr(self.image))
        self.assertIn('image_name', repr(self.image))

    def test_build(self):
        self.docker_client.build.return_value = self.stream
        self.image.build()
        self.docker_client.build.assert_called_once_with(
            'some/path', tag='image_name', rm=True)

    def test_push(self):
        self.docker_client.push.return_value = self.stream
        self.image.push('some-registry.domain.com', allow_insecure='testing')
        self.docker_client.push.assert_called_once_with(
            'some-registry.domain.com/image_name', insecure_registry='testing',
            stream=True)

    def test_pull(self):
        self.docker_client.pull.return_value = self.stream
        self.image.pull()
        self.docker_client.pull.assert_called_with(
            'image_name', insecure_registry=False, stream=True)
        self.image.pull('some-registry.domain.com', allow_insecure='testing')
        self.docker_client.pull.assert_called_with(
            'some-registry.domain.com/image_name', insecure_registry='testing',
            stream=True)


class TestContainer(BaseTest):
    def fake_container_create(self):
        self.container._docker_container_info = {
            u'Status': u'', u'Created': 1412867823,
            u'Image': u'{}:latest'.format(self.container.name), u'Ports': [],
            u'Command': u'ping localhost',
            u'Names': [u'/alice'],
            u'Id': u'183612dfe2c984e7363417dd7deb6c7a23e5eecfa5d5d9433be8',
        }

    def test_create(self):
        with self.assertRaisesRegexp(RuntimeError, 'not created'):
            self.container.id
        self.docker_client.create_container.return_value = {'Id': '1234'}
        self.container.create()
        self.assertEqual(self.container.id, '1234')
        # Not recreated:
        self.docker_client.create_container.return_value = {'Id': 'No!'}
        self.container.create()
        self.assertEqual(self.container.id, '1234')

    def assert_docker_create_with_group(self):
        expected_env = {
            'moose': 'overridden', 'pants': 'extra', 'more': 'extra extra'}
        self.docker_client.create_container.assert_called_once_with(
            'image_name', name='container_name',
            environment=expected_env, ports={'1111': None}.keys())

    def test_create_with_group(self):
        self.container.create(self.group)
        self.assert_docker_create_with_group()

    def assert_docker_start(self):
        self.docker_client.start.assert_called_once_with(
            self.container._docker_container_info,
            binds={'/tmp/': {'bind': '/normalised/local/foo/', 'ro': False}},
            links={'dependency_name': 'dependency_alias'},
            port_bindings={'1111': '2222'},
            privileged=True,
            network_mode='host')

    def test_start(self):
        self.fake_container_create()
        self.container.start()
        self.assert_docker_start()

    def assert_docker_start_with_group(self):
        self.docker_client.start.assert_called_once_with(
            self.container._docker_container_info,
            binds={'/tmp/': {'bind': '/normalised/local/bar/', 'ro': False}},
            links={'dependency_name': 'dependency_alias'},
            port_bindings={'1111': '2222'},
            privileged=True,
            network_mode='host')

    def test_start_with_group(self):
        self.fake_container_create()
        self.container.start(self.group)
        self.assert_docker_start_with_group()

    def test_run(self):
        self.container.run()
        self.assert_docker_start()

    def test_run_with_group(self):
        self.container.run(self.group)
        self.assert_docker_create_with_group()
        self.assert_docker_start_with_group()

    def test_stop(self):
        self.fake_container_create()
        self.container.stop()
        self.assertTrue(self.docker_client.stop.called)

    def test_status(self):
        self.container.status()
        self.fake_container_create()
        self.container.status()
        self.container._docker_container_info['Status'] = 'Up'
        self.container.status()

    def test_remove(self):
        self.fake_container_create()
        response = Mock()
        response.status_code = 200
        self.docker_client.remove_container.side_effect = (
            docker.errors.APIError("Arg, things broke", response=response))
        self.container.remove()
        self.assertTrue(self.docker_client.remove_container.called)


class TestCluster(BaseTest):
    def test_attach(self):
        stream = 'hello', 'world'
        self.docker_client.attach.return_value = stream
        term = Mock(spec=Terminal)
        self.cluster.attach(term)
        term.print_step.assert_has_calls(
            [call(self.container.name), call(self.dependency.name)],
            any_order=True)
        term.print_line.assert_has_calls([call('hello'), call('world')] * 2)
        term.print_warning.has_calls([
            call('{}: detached'.format(self.container.name)),
            call('{}: detached'.format(self.dependency.name)),
            call('All containers detached')], any_order=True)

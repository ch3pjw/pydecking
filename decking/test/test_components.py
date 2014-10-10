from unittest import TestCase
from mock import Mock, MagicMock, call

import os
import docker

from decking.terminal import Terminal
from decking.components import Image, Container, ContainerData, Group, Cluster

here = os.path.dirname(__file__)


class BaseTest(TestCase):
    def setUp(self):
        self.docker_client = MagicMock(spec=docker.Client)
        self.image = Image(self.docker_client, 'image_name', 'some/path')
        self.container = Container(
            self.docker_client, 'container_name', self.image,
            port_bindings={'1111': '2222'}, environment={'moose': 'pants'},
            net='host', privileged=True, volume_bindings={'./tmp/foo/:/tmp/'})
        self.cluster = Cluster(
            self.docker_client, 'cluster_name', [self.container])


class TestImage(BaseTest):
    def test_parse_dockerfile(self):
        path = os.path.join(here, 'data', 'alice', 'Dockerfile')
        result = Image._parse_dockerfile(path)
        self.assertEqual(result, ['ubuntu'])

    def test_caching_dependencies(self):
        self.image._parse_dockerfile = lambda path: ['some dep']
        self.assertEqual(self.image.dependencies, ['some dep'])
        self.image._parse_dockerfile = lambda path: ['unread dep']
        self.assertEqual(self.image.dependencies, ['some dep'])

    def test_repr(self):
        self.assertIn('Image', repr(self.image))
        self.assertIn('image_name', repr(self.image))


class TestContainer(BaseTest):
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

    def test_create_with_group(self):
        group = Group(
            name='fluffy',
            options=ContainerData(
                'unimportant', environment={
                    'moose': 'overridden', 'pants': 'extra'}),
            per_container_specs={
                'alice': ContainerData(
                    'never used', environment={'moose': 'llama'}),
                'container_name': ContainerData(
                    'never used', environment={'more': 'extra extra'})})
        self.container.create(group)
        expected_env = Container._format_environment({
            'moose': 'overridden', 'pants': 'extra', 'more': 'extra extra'})
        expected_env = {
            'moose': 'overridden', 'pants': 'extra', 'more': 'extra extra'}
        self.docker_client.create_container.assert_called_once_with(
            'image_name', name='container_name',
            environment=expected_env, ports=['1111'])



class TestCluster(BaseTest):
    def test_attach(self):
        stream = ['hello', 'world']
        self.docker_client.attach.return_value = stream
        term = Mock(spec=Terminal)
        self.cluster.attach(term)
        term.print_step.assert_called_with(self.container.name)
        term.print_line.assert_has_calls([call('hello'), call('world')])
        term.print_warning.has_calls([
            call('{}: detached'.format(self.container.name)),
            call('All containers detached')])

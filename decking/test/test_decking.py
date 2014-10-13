from unittest import TestCase
from mock import MagicMock
import os
from copy import deepcopy
import docker

from ..runner import Decking
from ..main import _read_config

here = os.path.dirname(__file__)


class TestDecking(TestCase):
    def assertCountEqual(self, *args, **kwargs):
        try:
            method = super(TestDecking, self).assertCountEqual
        except AttributeError:
            # Python <3
            method = super(TestDecking, self).assertItemsEqual
        return method(*args, **kwargs)

    @classmethod
    def setUpClass(cls):
        path = os.path.join(here, 'data', 'example_decking_file.json')
        # Implicitly tests config validation:
        cls._decking_config = _read_config(path)

    def setUp(self):
        # Protect tests from interfering by mutating config:
        self.decking_config = deepcopy(self._decking_config)
        self.docker_client = MagicMock(spec=docker.Client)

    def test_config_processing(self):
        base_path = os.path.join(os.sep, 'somewhere')
        decking = Decking(self.decking_config, base_path, self.docker_client)
        # Images:
        for name in 'alice', 'bob':
            expected = os.path.join(base_path, name)
            self.assertEqual(decking.images['repo/' + name].path, expected)
        # Containers:
        cont = decking.containers['alice']
        self.assertEqual(cont.name, 'alice')
        self.assertIs(cont.image, decking.images['repo/alice'])
        self.assertEqual(cont.port_bindings, {'1234': '2345'})
        cont = decking.containers['bob1']
        self.assertEqual(cont.environment, {'SOME_VAR': "'hello world'"})
        self.assertEqual(cont.net, 'host')
        self.assertEqual(
            cont.dependencies, {decking.containers['alice']: 'alice_alias'})
        expected = {os.path.join(base_path, 'tmp', 'bob1'): '/tmp'}
        self.assertEqual(cont.volume_bindings, expected)
        cont = decking.containers['bob2']
        self.assertEqual(cont.port_bindings, {'2222': '1111'})
        # Groups:
        group = decking.groups['additional_config']
        self.assertEqual(
            group.options.environment, {'SOME_VAR': "'not world'"})
        self.assertEqual(group.per_container_specs[cont].net, 'host')
        self.assertEqual(group.per_container_specs[cont].privileged, True)
        # Clusters:
        self.assertEqual(
            decking.clusters['vanilla'].containers,
            [decking.containers[name] for name in ('alice', 'bob1', 'bob2')])
        self.assertEqual(
            decking.clusters['with_group'].containers,
            [decking.containers[name] for name in ('alice', 'bob2')])
        self.assertIs(
            decking.clusters['with_group'].group,
            decking.groups['additional_config'])

    def test_live_container_info(self):
        live_data = [
            {
                u'Status': u'', u'Created': 1412867823,
                u'Image': u'repo/alice_image:latest', u'Ports': [],
                u'Command': u'ping localhost',
                u'Names': [u'/alice'],
                u'Id': u'183612dfe2c984e7363417dd7deb6c7a23e5eecfa5d5d9433be8',
            },
            {
                u'Status': u'', u'Created': 1412867769,
                u'Image': u'repo/bob1:latest', u'Ports': [],
                u'Command': u'ping localhost',
                u'Names': [u'/bob1'],
                u'Id': u'7295655e7ff050bddbac5d72e5dc289eb1fad8fd008e2e0ed552',
            }
        ]
        self.docker_client.containers.return_value = live_data
        decking = Decking(
            self.decking_config, docker_client=self.docker_client)
        self.assertTrue(decking.containers['alice'].created)
        self.assertTrue(decking.containers['bob1'].created)
        self.assertFalse(decking.containers['bob2'].created)

    def image_operation_helper(self, method_name, *args, **kwargs):
        base_path = os.path.join(here, 'data')
        decking = Decking(
            self.decking_config, base_path, self.docker_client)
        method = getattr(decking, method_name)
        def expected(*names):
            return [decking.images['repo/' + name] for name in names]
        processed = method('all', *args, **kwargs)
        self.assertCountEqual(processed, expected('unused', 'alice', 'bob'))
        processed = method('vanilla', *args, **kwargs)
        self.assertEqual(processed, expected('alice', 'bob'))
        processed = method('repo/bob', *args, **kwargs)
        self.assertEqual(processed, expected('bob'))
        self.assertRaisesRegexp(
            ValueError, 'tosh', method, 'tosh', *args, **kwargs)
        return decking

    def test_build(self):
        self.image_operation_helper('build')

    def test_push(self):
        decking = self.image_operation_helper('push', 'some-repo.domain.com')
        self.assertRaises(TypeError, decking.push)

    def test_pull(self):
        self.image_operation_helper('pull')

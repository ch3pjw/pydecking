from unittest import TestCase
from mock import MagicMock, patch, Mock
import os
from copy import deepcopy
import docker

from ..runner import Decking
from ..main import _read_config

here = os.path.dirname(__file__)


class TestDecking(TestCase):
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
            expected = os.path.join(base_path, name, 'Dockerfile')
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


@patch('time.sleep', lambda *a: None)
class OldTestDecking(TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(here, 'data', 'example_decking_file.json')
        # Implicitly tests config validation:
        cls._decking_config = _read_config(path)

    def setUp(self):
        # Protect tests from interfering by mutating config:
        self.decking_config = deepcopy(self._decking_config)
        self.mock_docker_client = MagicMock(spec=docker.Client, instance=True)
        self.container_ids = 'abcd1234', 'efab5678', 'cdef9012'
        self.container_infos = [{'Id': id_} for id_ in self.container_ids]

    def test_build_image(self):
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock(),
            base_path=os.path.join(here, 'data'))
        built = runner.build('all')
        self.assertEqual(built, ['repo/alice', 'repo/bob'])

    def cluster_create_setup(self):
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        self.mock_docker_client.create_container.side_effect = (
            self.container_infos)
        return runner

    def test_create_cluster(self):
        runner = self.cluster_create_setup()
        created = runner.create_cluster('vanilla')
        self.assertItemsEqual(created, ['alice', 'bob1', 'bob2'])
        created_infos = [
            spec['instance'] for spec in runner.container_specs.values()]
        self.assertEqual(
            runner.container_specs['alice']['instance'],
            self.container_infos[0])
        # A little bit ciruclar, but we check the 'Id's get created correctly:
        self.assertItemsEqual(created_infos, self.container_infos)

    def test_create_cluster_with_group(self):
        runner = self.cluster_create_setup()
        created = runner.create_cluster('with_group')
        # Created in dependency order:
        self.assertEqual(created, ['alice', 'bob2'])
        self.assertEqual(
            runner.container_specs['alice']['instance'],
            self.container_infos[0])
        self.assertEqual(
            runner.container_specs['bob2']['instance'],
            self.container_infos[1])

    def test_groups_affect_specs(self):
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        container_specs = runner._build_dynamic_container_specs_for_cluster(
            runner.cluster_specs['with_group'], runner.container_specs,
            runner.group_specs)
        for container in container_specs.values():
            self.assertEqual(container['env'], ["SOME_VAR='not world'"])
        self.assertEqual(container_specs['bob2']['net'], 'host')

    def _prepare_run(self, runner):
        for i, name in enumerate(('alice', 'bob1', 'bob2')):
            runner.container_specs[name]['instance'] = self.container_infos[i]

    def test_start_cluster(self):
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        self.assertRaisesRegexp(
            RuntimeError, 'Must create', runner.start_cluster, 'vanilla')
        self._prepare_run(runner)
        runner.start_cluster('vanilla')

    def test_cluster_not_found(self):
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        self._prepare_run(runner)
        self.assertRaisesRegexp(
            ValueError, "Undefined cluster.*pub", runner.start_cluster, 'pub')

    def test_bad_dependencies(self):
        self.decking_config.update({
            'containers': {
                'zen': {
                    'image': 'repo/zen',
                    'dependencies': ['zen:zen_alias']
                }
            },
            'clusters': {
                'dojo': ['zen']
            }
        })
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        self.assertRaisesRegexp(
            RuntimeError, 'dependencies', runner.start_cluster, 'dojo')
        self.decking_config.update({
            'containers': {
                'zen': {
                    'image': 'repo/zen',
                    'dependencies': ['yen:yen_alias']
                },
                'yen': {
                    'image': 'repo/yen',
                    'dependencies': ['zen:zen_alias']
                }
            },
            'clusters': {
                'dojo': ['zen', 'yen']
            }
        })
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        self.assertRaisesRegexp(
            RuntimeError, 'dependencies', runner.start_cluster, 'dojo')

    def _test_pull(self, registry, allow_insecure):
        remote_image_path = image_path = 'some_repo/zen'
        if registry:
            remote_image_path = '{}/{}'.format(registry, image_path)

        self.decking_config.update({
            'containers': {
                'zen': {
                    'image': image_path,
                }
            },
            'clusters': {
                'dojo': ['zen']
            }
        })
        runner = Decking(
            self.decking_config, self.mock_docker_client, terminal=Mock())
        runner.pull_cluster(
            cluster='dojo',
            registry=registry,
            allow_insecure=allow_insecure)

        self.mock_docker_client.pull.assert_called_once_with(
            remote_image_path, insecure_registry=allow_insecure, stream=True)
        if registry:
            self.mock_docker_client.tag.assert_called_once_with(
                remote_image_path, image_path)
            self.mock_docker_client.remove_image.assert_called_once_with(
                remote_image_path)
        else:
            self.assertFalse(self.mock_docker_client.tag.called)
            self.assertFalse(self.mock_docker_client.remove_image.called)

    def test_pull_repo(self):
        self._test_pull('foobar', False)

    def test_pull_no_repo(self):
        self._test_pull(None, False)

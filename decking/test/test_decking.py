from unittest import TestCase
from mock import MagicMock, patch, Mock
import os
from copy import deepcopy
import docker

from ..runner import Decking
from ..main import _read_config

here = os.path.dirname(__file__)


@patch('time.sleep', lambda *a: None)
class TestDecking(TestCase):
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

    def test_uncolon_mapping(self):
        self.assertEqual(
            Decking._uncolon_mapping(['a:b', 'c:d']),
            {'a': 'b', 'c': 'd'})

    def test_filter_dict_by_keys(self):
        result = Decking._filter_dict_by_keys(
            {'a': 'hello', 'b': 'world', 'c': 'toast'}, ['a', 'c'])
        self.assertEqual(result, {'a': 'hello', 'c': 'toast'})

    def test_parse_dockerfile(self):
        with open(os.path.join(here, 'data', 'alice', 'Dockerfile')) as f:
            result = Decking._parse_dockerfile(f)
        self.assertEqual(result, 'ubuntu')

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

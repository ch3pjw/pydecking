from unittest import TestCase
from mock import MagicMock, patch
import os
import docker

from ..runner import Decking

here = os.path.dirname(__file__)


@patch('time.sleep', lambda *a: None)
class TestDecking(TestCase):
    def setUp(self):
        self.decking_config = {
            'images': {
                'repo/alice': os.path.join(here, 'data', 'alice'),
                'repo/bob': os.path.join(here, 'data', 'bob')
            },
            'containers': {
                'alice': {
                    'image': 'repo/alice',
                    'dependencies': ['bob:bob_alias'],
                    'port': ['1234:2345']
                },
                'bob': {
                    'image': 'repo/bob',
                    'env': ['A=b']
                }
            },
            'clusters': {
                'office': ['alice', 'bob']
            }
        }
        self.mock_docker_client = MagicMock(spec=docker.Client, instance=True)
        self.container_info_1 = {'Id': 'abcd1234'}
        self.container_info_2 = {'Id': 'efab5678'}

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
        runner = Decking(self.decking_config, self.mock_docker_client)
        built = runner.build('all')
        self.assertEqual(built, ['repo/alice', 'repo/bob'])

    def test_create_cluster(self):
        runner = Decking(self.decking_config, self.mock_docker_client)
        self.mock_docker_client.create_container.side_effect = [
            self.container_info_1, self.container_info_2]
        created = runner.create_cluster('office')
        self.assertEqual(created, ['bob', 'alice'])
        self.assertEqual(
            runner.container_specs['bob']['instance'], self.container_info_1)
        self.assertEqual(
            runner.container_specs['alice']['instance'], self.container_info_2)

    def _prepare_run(self, runner):
        runner.container_specs['bob']['instance'] = self.container_info_1
        runner.container_specs['alice']['instance'] = self.container_info_2

    def test_start_cluster(self):
        runner = Decking(self.decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'Must create', runner.start_cluster, 'office')
        self._prepare_run(runner)
        runner.start_cluster('office')

    def test_cluster_not_found(self):
        runner = Decking(self.decking_config, self.mock_docker_client)
        self._prepare_run(runner)
        self.assertRaisesRegexp(
            ValueError, "Undefined cluster.*pub", runner.start_cluster, 'pub')

    def test_bad_depenencies(self):
        decking_config = {
            'containers': {
                'zen': {
                    'image': 'repo/zen',
                    'dependencies': ['zen:zen_alias']
                }
            },
            'clusters': {
                'dojo': ['zen']
            }
        }
        runner = Decking(decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'dependencies', runner.start_cluster, 'dojo')
        decking_config = {
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
        }
        runner = Decking(decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'dependencies', runner.start_cluster, 'dojo')

    def _test_pull(self, registry):
        remote_image_path = image_path = 'some_repo/zen'
        if registry:
            remote_image_path = '{}/{}'.format(registry, image_path)

        decking_config = {
            'containers': {
                'zen': {
                    'image': image_path,
                }
            },
            'clusters': {
                'dojo': ['zen']
            }
        }
        runner = Decking(decking_config, self.mock_docker_client)
        runner.pull_cluster(cluster='dojo', registry=registry)

        self.mock_docker_client.pull.assert_called_once_with(remote_image_path)
        if registry:
            self.mock_docker_client.tag.assert_called_once_with(
                remote_image_path, image_path)
            self.mock_docker_client.remove_image.assert_called_once_with(
                remote_image_path)
        else:
            self.assertFalse(self.mock_docker_client.tag.called)
            self.assertFalse(self.mock_docker_client.remove_image.called)

    def test_pull_repo(self):
        self._test_pull('foobar')

    def test_pull_no_repo(self):
        self._test_pull(None)

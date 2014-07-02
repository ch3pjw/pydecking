from unittest import TestCase
from mock import MagicMock, patch
import docker

from runner import DeckingRunner


@patch('time.sleep')
class TestDeckingRunner(TestCase):
    def setUp(self):
        self.decking_config = {
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

    def test_uncolon_mapping(self, sleep_mock):
        self.assertEqual(
            DeckingRunner._uncolon_mapping(['a:b', 'c:d']),
            {'a': 'b', 'c': 'd'})

    def test_create(self, sleep_mock):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        self.mock_docker_client.create_container.side_effect = [
            self.container_info_1, self.container_info_2]
        created = runner.create('office')
        self.assertEqual(created, ['bob', 'alice'])
        self.assertEqual(
            self.decking_config['containers']['bob']['instance'],
            self.container_info_1)
        self.assertEqual(
            self.decking_config['containers']['alice']['instance'],
            self.container_info_2)

    def _prepare_run(self):
        self.decking_config['containers']['bob']['instance'] = (
            self.container_info_1)
        self.decking_config['containers']['alice']['instance'] = (
            self.container_info_2)

    def test_run(self, sleep_mock):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'Must create', runner.start, 'office')
        self._prepare_run()
        runner.start('office')

    def test_cluster_not_found(self, sleep_mock):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        self._prepare_run()
        self.assertRaisesRegexp(
            ValueError, "wasn't found", runner.start, 'pub')

    def test_bad_dependencies(self, sleep_mock):
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
        runner = DeckingRunner(decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'dependencies', runner.start, 'dojo')
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
        runner = DeckingRunner(decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'dependencies', runner.start, 'dojo')

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
        runner = DeckingRunner(decking_config, self.mock_docker_client)
        runner.pull(registry)

        self.mock_docker_client.pull.assert_called_once_with(remote_image_path)
        if registry:
            self.mock_docker_client.tag.assert_called_once_with(remote_image_path, image_path)
            self.mock_docker_client.remove_image.assert_called_once_with(remote_image_path)
        else:
            self.assertFalse(self.mock_docker_client.tag.called)
            self.assertFalse(self.mock_docker_client.remove_image.called)

    def test_pull_repo(self, sleep_mock):
        self._test_pull('foobar')

    def test_pull_no_repo(self, sleep_mock):
        self._test_pull(None)
        

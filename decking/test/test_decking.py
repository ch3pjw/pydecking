from unittest import TestCase
from mock import MagicMock, patch
import os
import docker

from ..runner import DeckingRunner

here = os.path.dirname(__file__)


@patch('time.sleep', lambda *a: None)
class TestDeckingRunner(TestCase):
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
            DeckingRunner._uncolon_mapping(['a:b', 'c:d']),
            {'a': 'b', 'c': 'd'})

    def test_filter_dict_by_keys(self):
        result = DeckingRunner._filter_dict_by_keys(
            {'a': 'hello', 'b': 'world', 'c': 'toast'}, ['a', 'c'])
        self.assertEqual(result, {'a': 'hello', 'c': 'toast'})

    def test_parse_dockerfile(self):
        with open(os.path.join(here, 'data', 'alice', 'Dockerfile')) as f:
            result = DeckingRunner._parse_dockerfile(f)
        self.assertEqual(result, 'ubuntu')

    def test_build(self):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        built = runner.build('all')
        self.assertEqual(built, ['repo/alice', 'repo/bob'])

    def test_create(self):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        self.mock_docker_client.create_container.side_effect = [
            self.container_info_1, self.container_info_2]
        created = runner.create('office')
        self.assertEqual(created, ['bob', 'alice'])
        self.assertEqual(
            runner.container_specs['bob']['instance'], self.container_info_1)
        self.assertEqual(
            runner.container_specs['alice']['instance'], self.container_info_2)

    def _prepare_run(self, runner):
        runner.container_specs['bob']['instance'] = self.container_info_1
        runner.container_specs['alice']['instance'] = self.container_info_2

    def test_start(self):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        self.assertRaisesRegexp(
            RuntimeError, 'Must create', runner.start, 'office')
        self._prepare_run(runner)
        runner.start('office')

    def test_cluster_not_found(self):
        runner = DeckingRunner(self.decking_config, self.mock_docker_client)
        self._prepare_run(runner)
        self.assertRaisesRegexp(
            ValueError, "Undefined cluster.*pub", runner.start, 'pub')

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

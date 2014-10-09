from unittest import TestCase

from decking.util import delimit_mapping, undelimit_mapping, iter_dependencies


class TestUtil(TestCase):
    def test_delimit_mapping(self):
        self.assertItemsEqual(
            delimit_mapping({'a': 1, 'b': 2}), ['a=1', 'b=2'])

    def test_undelimit_mapping(self):
        self.assertEqual(
            undelimit_mapping(['a:b', 'c:d']),
            {'a': 'b', 'c': 'd'})
        self.assertEqual(
            undelimit_mapping(['a=b', 'c=d'], delimiter='='),
            {'a': 'b', 'c': 'd'})

    def test_iter_dependencies(self):
        data = {
            'a': {'dependencies': ['b', 'c']},
            'b': {'dependencies': ['c']},
            'c': {}
        }
        def get_item_dependencies(key):
            return data[key].get('dependencies', [])
        self.assertEqual(
            tuple(iter_dependencies(data, get_item_dependencies)),
            ('c', 'b', 'a'))
        data = {
            'a': {'dependencies': 'b'},
            'b': {'dependencies': 'a'}
        }
        with self.assertRaisesRegexp(RuntimeError, 'Circular'):
            for item in iter_dependencies(data, get_item_dependencies):
                pass

from collections import Mapping, Sequence
from cerberus import Validator, errors

try:
    string_type = basestring
except NameError:
    # Python 3
    string_type = str


class ConfigValidator(Validator):
    _cluster_config_dict_schema = {
        'group': {'type': 'string'},
        'containers': {'type': 'list'}
    }

    def _validate_type_cluster(self, field, value):
        if isinstance(value, Sequence):
            for name in value:
                if not isinstance(name, string_type):
                    self._error(
                        field, 'cluster definition list item {} is not a '
                        'container name'.format(name))
        elif isinstance(value, Mapping):
            self._validate_schema(
                self._cluster_config_dict_schema, field, value)
        else:
            self._error(field, errors.ERROR_BAD_TYPE % 'Mapping or Sequence')


_container_schema_common = {
    'port': {
        'type': 'list',
        'schema': {'type': 'string'}
    },
    'env': {
        'type': 'list',
        'schema': {'type': 'string'}
    },
    'dependencies': {
        'type': 'list',
        'schema': {'type': 'string'}
    },
    'mount': {
        'type': 'list',
        'schema': {'type': 'string'}
    },
    'net': {
        'type': 'string'
    },
    'privileged': {
        'type': 'boolean',
    }
}

schema = {
    'images': {
        'type': 'dict',
        'keyschema': {
            'type': 'string'
        }
    },
    'clusters': {
        'type': 'dict',
        'keyschema': {
            'type': 'cluster',
        }
    },
    'containers': {
        'type': 'dict',
        'required': True,
        'keyschema': {
            'type': 'dict',
            'schema': dict(
                image={
                    'type': 'string',
                    'required': True
                }, **_container_schema_common),
            },
        },
    'groups': {
        'type': 'dict',
        'keyschema': {
            'type': 'dict',
            'schema': {
                'options': {
                    'type': 'dict',
                    'schema': _container_schema_common
                },
                'containers': {
                    'type': 'dict',
                    'keyschema': {
                        'type': 'dict',
                        'schema': _container_schema_common
                    }
                }
            }
        }
    }
}

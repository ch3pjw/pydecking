import json

from decking.terminal import term


def delimit_mapping(mapping, delimiter=':'):
    '''
    Takes a mapping and turns it into a sequence of strings of the form:
      ['a:b', 'c:d']
    '''
    format_string = '{}' + delimiter + '{}'
    return map(lambda item: format_string.format(*item), mapping.items())


def undelimit_mapping(
        mapping_as_sequence, delimiter=':', reverse_mapping=False):
    '''
    Takes a squence of strings of the form:
      ['a:b', 'c:d']
    and translates it into the form:
      {'a': 'b', 'c': 'd'}

    :paremeter bool reverse_mapping: specifies whether 'a:b' -> {'a': 'b'} or
        {'b': 'a'}

    This is useful because of how decking specified mappings for things like
    ports.
    '''
    generator = (item.split(delimiter, 1) for item in mapping_as_sequence)
    if reverse_mapping:
        return {v: k for k, v in generator}
    else:
        return dict(generator)


def consume_stream(stream):
    for item in stream:
        item = json.loads(item)
        if 'stream' in item:
            for line in item['stream'].strip().splitlines():
                term.print_line(line)
        elif 'status' in item:
            # TODO: report progress
            pass
        elif 'error' in item:
            raise RuntimeError(item['error'])


def iter_dependencies(to_process, get_item_dependencies):
    '''Generator that yields sets of objects from 'to_process' such that each
    object in each set has already had its dependency objects yielded (and
    therefore 'processed') in a previous set.
    '''
    to_process = set(to_process)
    processed = set()
    while to_process:
        pending = set()
        for item in list(to_process):
            if all(dep in processed for dep in get_item_dependencies(item)):
                to_process.remove(item)
                pending.add(item)
                yield item
        if not pending:
            raise RuntimeError('Circular dependencies?')
        processed |= pending

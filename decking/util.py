import json

from decking.terminal import term


def undelimit_mapping(mapping_as_sequence, delimiter=':'):
    '''
    Takes a squence of strings of the form:
      ['a:b', 'c:d']
    and translates it into the form:
      {'a': 'b', 'c': 'd'}

    This is useful because of how decking specified mappings for things like
    ports.
    '''
    return dict(item.split(delimiter, 1) for item in mapping_as_sequence)


def consume_stream(stream):
    prev_status_id = None
    for item in stream:
        item = json.loads(item)
        if 'stream' in item:
            for line in item['stream'].strip().splitlines():
                term.print_line(line)
        elif 'status' in item:
            status = item.pop('status')
            status_id = item.pop('id', None)
            msg = status
            if status_id:
                msg += ' ({})'.format(status_id)
            if prev_status_id == status_id:
                call = term.replace_line
            else:
                call = term.print_line
            if 'progress' in item:
                msg += ': ' + item['progress']
            else:
                msg += ' ' + ' '.join(
                    '{}: {}'.format(k, v)
                    for k, v in item.iteritems()
                    if v)
            call(msg)
            prev_status_id = status_id

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
            raise RuntimeError('Missing or circular dependencies')
        processed |= pending

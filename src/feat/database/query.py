import sys

from zope.interface import Interface, implements, Attribute

from feat.common import serialization, enum, first, defer
from feat.database import view

from feat.database.interface import IViewFactory


class IPlanBuilder(Interface):

    def get_basic_queries():
        '''
        Returns a list of tuples: (field, operator, value)
        '''


class IQueryViewFactory(IViewFactory):

    fields = Attribute('C{list} of unicode names of fields of the query')


class Evaluator(enum.Enum):
    '''
    equals: ==
    le: <=
    ge: >=
    between: conjuntion of start_key and end_key
    inside: reflects usage of multiple keys, or python code x in [...]
    none: special value used by sorting operator, fetches the whole index range
    '''

    equals, le, ge, between, inside, none = range(6)


@serialization.register
class Condition(serialization.Serializable):

    implements(IPlanBuilder)

    type_name = 'condition'

    def __init__(self, field, oper, value):
        self.field = field
        self.operator = oper
        self.value = value

    ### IPlanBuilder ###

    def get_basic_queries(self):
        return [(self.field, self.operator, self.value)]


class Operator(enum.Enum):

    AND, OR = range(2)


class Direction(enum.Enum):

    ASC, DESC = range(2)


@serialization.register
class Query(serialization.Serializable):

    implements(IPlanBuilder)

    type_name = 'query'

    def __init__(self, factory, *parts, **kwargs):
        self.factory = IQueryViewFactory(factory)

        self.parts = []
        self.operators = []
        if len(parts) == 0:
            raise ValueError("Empty query?")

        for part, index in zip(parts, range(len(parts))):
            if index % 2 == 0:
                if not IPlanBuilder.providedBy(part):
                    raise ValueError("Element at index %d should be a Query or"
                                     " condition, %r given" % (index, part))
                for query in part.get_basic_queries():
                    if query[0] not in factory.fields:
                        raise ValueError("Unknown query field: '%s'" %
                                         (query[0], ))
                self.parts.append(part)

            if index % 2 == 1:
                if not isinstance(part, Operator):
                    raise ValueError("Element at index %d should be an "
                                     "Operator, %r given" % (index, part))
                self.operators.append(part)

        self.sorting = kwargs.pop('sorting', None)
        bad_sorting = ("Sorting should be a list of tuples: (field, direction)"
                       ", %r given" % (self.sorting, ))
        if self.sorting is None:
            # default sorting to by all the fields in ascending order
            self.sorting = [(field, Direction.ASC)
                            for field, _, __ in self.get_basic_queries()]

        if not isinstance(self.sorting, (list, tuple)):
            raise ValueError(bad_sorting)
        for part in self.sorting:
            if not isinstance(part, (list, tuple)) or len(part) != 2:
                raise ValueError(bad_sorting)
            if not isinstance(part[0], (str, unicode)):
                raise ValueError(bad_sorting)
            if not isinstance(part[1], Direction):
                raise ValueError(bad_sorting)

        if kwargs:
            raise ValueError('Uknown keywords: %s' % (kwargs.keys(), ))

    ### IPlanBuilder ###

    def get_basic_queries(self):
        temp = list()
        for part in self.parts:
            temp.extend(part.get_basic_queries())

        # if we want to sort by the field which is not available in the query
        # we will need to query for the full range of the index
        if self.sorting:
            for sortby, _ in self.sorting:
                included = first(x[0] for x in temp if x[0] == sortby)
                if not included:
                    temp.append((sortby, Evaluator.none, None))

        # remove duplicates
        resp = list()
        while temp:
            x = temp.pop(0)
            if x not in resp:
                resp.append(x)

        return resp


@defer.inlineCallbacks
def select(connection, query):
    temp, responses = yield _get_query_response(connection, query)
    if query.sorting:
        temp = sorted(temp, key=_generate_sort_key(responses, query.sorting))
    else:
        temp = list(temp)
    fetched = yield connection.bulk_get(temp)
    defer.returnValue(fetched)


@defer.inlineCallbacks
def count(connection, query):
    temp, responses = yield _get_query_response(connection, query)
    defer.returnValue(len(temp))


### private ###


@defer.inlineCallbacks
def _get_query_response(connection, query):
    info = yield connection.info()
    update_seq = info['update_seq']

    cache = connection.get_query_cache()
    responses = dict()
    for subquery in query.get_basic_queries():
        # subquery -> list of doc ids
        responses[subquery] = yield cache.query(
            connection, query.factory, subquery, update_seq)
    defer.returnValue((_calculate_query_response(responses, query), responses))


def _calculate_query_response(responses, query):
    for_parts = []

    for part in query.parts:
        if isinstance(part, Condition):
            for_parts.append(set(responses[part.get_basic_queries()[0]]))
        elif isinstance(part, Query):
            for_parts.append(_calculate_query_response(responses, part))
    operators = list(query.operators)
    while True:
        if len(for_parts) == 1:
            return for_parts[0]
        oper = operators.pop(0)
        if oper == Operator.AND:
            for_parts[0] = for_parts[0].intersection(for_parts.pop(1))
        elif oper == Operator.OR:
            for_parts[0] = for_parts[0].union(for_parts.pop(1))
        else:
            raise ValueError("Unkown operator '%r' %" (oper, ))


def _generate_sort_key(responses, sorting):

    def sort_key(row):
        positions = list()

        for name, direction in sorting:
            relevant = [v for k, v in responses.iteritems()
                        if k[0] == name]
            for r in relevant:
                try:
                    index = r.index(row)
                    break
                except ValueError:
                    continue
            else:
                index = sys.maxint
            if direction == Direction.DESC:
                index = -index
            positions.append(index)

        return tuple(positions)

    return sort_key


def _generate_keys(field, evaluator, value):
    if evaluator == Evaluator.equals:
        return dict(key=(field, value))
    if evaluator == Evaluator.le:
        return dict(endkey=(field, value))
    if evaluator == Evaluator.ge:
        return dict(startkey=(field, value))
    if evaluator == Evaluator.between:
        return dict(startkey=(field, value[0]), endkey=(field, value[1]))
    if evaluator == Evaluator.inside:
        return dict(keys=[(field, x) for x in value])
    if evaluator == Evaluator.none:
        return dict(startkey=(field, ), endkey=(field, {}))

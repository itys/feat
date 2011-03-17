# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy
import operator

from feat.common import serialization, formatable


@serialization.register
class BaseMessage(formatable.Formatable):

    formatable.field('reply_to', None)
    formatable.field('message_id', None)
    formatable.field('protocol_id', None)
    formatable.field('protocol_type', None)
    formatable.field('expiration_time', None)
    formatable.field('sender_id', None)
    formatable.field('receiver_id', None)
    formatable.field('payload', dict())

    def clone(self):
        return copy.deepcopy(self)

    def __repr__(self):
        d = dict()
        for field in self._fields:
            d[field.name] = getattr(self, field.name)
        return "<%r, %r>" % (type(self), d)


@serialization.register
class ContractMessage(BaseMessage):

    formatable.field('protocol_type', 'Contract')


@serialization.register
class RequestMessage(BaseMessage):

    formatable.field('protocol_type', 'Request')


@serialization.register
class ResponseMessage(BaseMessage):

    formatable.field('protocol_type', 'Request')


# messages send by menager to contractor


@serialization.register
class Announcement(ContractMessage):
    pass


@serialization.register
class Rejection(ContractMessage):
    pass


@serialization.register
class Grant(ContractMessage):

     # set it to number to receive frequent reports
    formatable.field('update_report', None)


@serialization.register
class Cancellation(ContractMessage):

    # why do we cancel?
    formatable.field('reason', None)


@serialization.register
class Acknowledgement(ContractMessage):
    pass


# messages sent by contractor to manager


@serialization.register
class Bid(ContractMessage):

    @staticmethod
    def pick_best(bids, number=1):
        '''
        Picks the cheapest bids from the list provided.
        @param bids: list of bids to choose from
        @param number: number of bids to choose
        @returns: the list of bids
        '''
        for bid in bids:
            assert isinstance(bid, Bid)

        costs = sorted(map(lambda x: (x.payload['cost'], x), bids),
                       key=operator.itemgetter(0))
        picked = list()

        for x in range(number):
            try:
                best, bid = costs.pop(0)
            except IndexError:
                break
            picked.append(bid)

        return picked


@serialization.register
class Refusal(ContractMessage):
    pass


@serialization.register
class UpdateReport(ContractMessage):
    pass


@serialization.register
class FinalReport(ContractMessage):
    pass

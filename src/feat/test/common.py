import functools
import uuid
import re
import inspect
import time

from twisted.internet import defer, reactor
from twisted.trial import unittest, util
from twisted.scripts import trial

from feat.agencies.emu import agency
from feat.agents import message, recipient
from feat.common import log, decorator
from feat.common import delay as delay_module

from . import factories

try:
    _getConfig = trial.getConfig
except AttributeError:
    # trial.getConfig() is only available when using flumotion-trial
    _getConfig = dict


log.FluLogKeeper.init('test.log')


def delay(value, delay):
    '''Returns a deferred triggered after the specified delay
    with the specified value.'''
    d = defer.Deferred()
    delay_module.callLater(delay, d.callback, value)
    return d


def break_chain(value):
    '''Breaks a deferred call chain ensuring the rest will be called
    asynchronously in the next reactor loop.'''
    return delay(value, 0)


def attr(*args, **kwargs):
    """Decorator that adds attributes to objects.

    It can be used to set the 'slow', 'skip', or 'todo' flags in test cases.
    """

    def wrap(func):
        for name in args:
            # these are just True flags:
            setattr(func, name, True)
        for name, value in kwargs.items():
            setattr(func, name, value)
        return func
    return wrap


class TestCase(unittest.TestCase, log.FluLogKeeper, log.Logger):

    log_category = "test"

    def __init__(self, methodName=' impossible-name '):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        # Twisted changed the TestCase.__init__ signature several
        # times.
        #
        # In versions older than 2.1.0 there was no __init__ method.
        #
        # In versions 2.1.0 up to 2.4.0 there is a __init__ method
        # with a methodName kwarg that has a default value of None.
        #
        # In version 2.5.0 the default value of the kwarg was changed
        # to "runTest".
        #
        # In versions above 2.5.0 God only knows what's the default
        # value, as we do not currently support them.
        import inspect
        if not inspect.ismethod(unittest.TestCase.__init__):
            # it's Twisted < 2.1.0
            unittest.TestCase.__init__(self)
        else:
            # it's Twisted >= 2.1.0
            if methodName == ' impossible-name ':
                # we've been called with no parameters, use the
                # default parameter value from the superclass
                defaults = inspect.getargspec(unittest.TestCase.__init__)[3]
                methodName = defaults[0]
            unittest.TestCase.__init__(self, methodName=methodName)

        # Skip slow tests if '--skip-slow' option is enabled
        if _getConfig().get('skip-slow'):
            if self.getSlow() and not self.getSkip():
                self.skip = 'slow test'

    def getSlow(self):
        """
        Return whether this test has been marked as slow. Checks on the
        instance first, then the class, then the module, then packages. As
        soon as it finds something with a C{slow} attribute, returns that.
        Returns C{False} if it cannot find anything.
        """

        return util.acquireAttribute(self._parents, 'slow', False)

    def cb_after(self, arg, obj, method):
        '''
        Returns defered fired after the call of method on object.
        Can be used in defered chain like this:

        d.addCallback(doSomeStuff)
        d.addCallback(self._cb_after, obj=something, method=some_method)
        d.addCallback(jobAfterCallOfSomeMethod)

        This will fire last callback after something.some_method has been
        called.
        Parameter passed to the last callback is either return value of
        doSomeStuff, or, if this is None, the return value of stubbed method.
        '''
        old_method = obj.__getattribute__(method)
        d = defer.Deferred()

        def new_method(*args, **kwargs):
            obj.__setattr__(method, old_method)
            ret = old_method(*args, **kwargs)
            reactor.callLater(0, d.callback, arg or ret)
            return ret

        obj.__setattr__(method, new_method)

        return d

    def assertCalled(self, obj, name, times=1, params=None):
        assert isinstance(obj, Mock), "Got: %r" % obj
        calls = obj.find_calls(name)
        times_called = len(calls)
        template = "Expected %s method to be called %d time(s), "\
                   "was called %d time(s)"
        self.assertEqual(times, times_called,\
                             template % (name, times, times_called))
        if params:
            for call in calls:
                self.assertEqual(len(params), len(call.args))
                for param, arg in zip(params, call.args):
                    self.assertTrue(isinstance(arg, param))

        return obj

    def assertIsInstance(self, _, klass):
        self.assertTrue(isinstance(_, klass),
             "Expected instance of %r, got %r instead" % (klass, _.__class__))
        return _

    def assertAsyncEqual(self, chain, expected, value, *args, **kwargs):
        '''Adds an asynchronous assertion to the specified deferred chain.
        If the chain deferred is None, a new fired one will be created.
        The checks are serialized and done in order of declaration.
        If the value is a Deferred, the check wait for its result,
        if not it compare rightaway.
        If value is a callable, it is called with specified arguments
        and keyword WHEN THE PREVIOUS CALL HAS BEEN DONE.

        Used like this::

          d = defer.succeed(None)
          d = self.assertAsyncEqual(d, EXPECTED, FIRED_DEFERRED)
          d = self.assertAsyncEqual(d, EXPECTED, VALUE)
          d = self.assertAsyncEqual(d, 42, asyncDouble(21))
          d = self.assertAsyncEqual(d, 42, asyncDouble, 21)
          return d

        Or::

          return self.assertAsyncEqual(None, EXPECTED, FIRED_DEFERRED)
        '''

        def retrieve(_, expected, value, args=None, kwargs=None):
            if isinstance(value, defer.Deferred):
                value.addCallback(check, expected)
                return value
            if callable(value):
                return retrieve(_, expected, value(*args, **kwargs))
            return check(value, expected)

        def check(result, expected):
            self.assertEqual(expected, result)
            return result

        if chain is None:
            chain = defer.succeed(None)

        return chain.addCallback(retrieve, expected, value, args, kwargs)

    def stub_method(self, obj, method, handler):
        handler = functools.partial(handler, obj)
        obj.__setattr__(method, handler)
        return obj

    def tearDown(self):
        delay.time_scale = 1

    def format_block(self, block):
        '''
        Format the given block of text, trimming leading/trailing
        empty lines and any leading whitespace that is common to all lines.
        The purpose is to let us list a code block as a multiline,
        triple-quoted Python string, taking care of indentation concerns.
        '''
        # separate block into lines
        lines = str(block).split('\n')
        # remove leading/trailing empty lines
        while lines and not lines[0]:
            del lines[0]
        while lines and not lines[-1]:
            del lines[-1]
        # look at first line to see how much indentation to trim
        ws = re.match(r'\s*', lines[0]).group(0)
        if ws:
            lines = map(lambda x: x.replace(ws, '', 1), lines)
        # remove leading/trailing blank lines (after leading ws removal)
        # we do this again in case there were pure-whitespace lines
        while lines and not lines[0]:
            del lines[0]
        while lines and not lines[-1]:
            del lines[-1]
        return '\n'.join(lines) + '\n'


class Mock(object):

    def __init__(self):
        self._called = []

    def find_calls(self, name):
        return filter(lambda x: x.name == name, self._called)

    @staticmethod
    def stub(method):

        def decorated(self, *args, **kwargs):
            call = MockCall(method.__name__, args, kwargs)
            self._called.append(call)

        return decorated


class MockCall(object):

    def __init__(self, name, args, kwargs):
        self.name = name
        self.args = args
        self.kwargs = kwargs


class AgencyTestHelper(object):

    protocol_type = None
    protocol_id = None

    def setUp(self):
        self.agency = agency.Agency()
        self.session_id = None

    def setup_endpoint(self):
        '''
        Sets up the destination for tested component to send messages to.

        @returns endpoint: Receipient instance pointing to the queue above
                           (use it for reply-to fields)
        @returns queue: Queue instance we use may .consume() on to get
                        messages from components being tested
        '''
        endpoint = recipient.Agent(str(uuid.uuid1()), 'lobby')
        queue = self.agency._messaging.defineQueue(endpoint.key)
        exchange = self.agency._messaging.defineExchange(endpoint.shard)
        exchange.bind(endpoint.key, queue)
        return endpoint, queue

    # methods for handling documents

    def doc_factory(self, doc_class, **options):
        '''Builds document of selected class and saves it to the database

        @returns: Document with id and revision set
        @return_type: subclass of feat.agents.document.Document
        '''
        document = factories.build(doc_class, **options)
        return self.agency._database.connection.save_document(document)

    # methods for sending and receiving custom messages

    def send_announce(self, manager):
        msg = message.Announcement()
        manager.medium.announce(msg)
        return manager

    def send_bid(self, contractor, bid=1):
        msg = message.Bid()
        msg.bids = [bid]
        contractor.medium.bid(msg)
        return contractor

    def send_refusal(self, contractor):
        msg = message.Refusal()
        contractor.medium.refuse(msg)
        return contractor

    def send_final_report(self, contractor):
        msg = message.FinalReport()
        contractor.medium.finalize(msg)
        return contractor

    def send_cancel(self, contractor, reason=""):
        msg = message.Cancellation()
        msg.reason = reason
        contractor.medium.defect(msg)
        return contractor

    def recv_announce(self, *_):
        msg = message.Announcement()
        msg.session_id = str(uuid.uuid1())
        self.session_id = msg.session_id
        return self.recv_msg(msg).addCallback(lambda ret: _)

    def recv_grant(self, _, bid_index=0, update_report=None):
        msg = message.Grant()
        msg.bid_index = bid_index
        msg.update_report = update_report
        msg.session_id = self.session_id
        return self.recv_msg(msg).addCallback(lambda ret: _)

    def recv_rejection(self, _):
        msg = message.Rejection()
        msg.session_id = self.session_id
        return self.recv_msg(msg).addCallback(lambda ret: _)

    def recv_cancel(self, _, reason=""):
        msg = message.Cancellation()
        msg.reason = reason
        msg.session_id = self.session_id
        return self.recv_msg(msg).addCallback(lambda ret: _)

    def recv_ack(self, _):
        msg = message.Acknowledgement()
        msg.session_id = self.session_id
        return self.recv_msg(msg).addCallback(lambda ret: _)

    def recv_msg(self, msg, reply_to=None, key='dummy-contract',
                  expiration_time=None):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        msg.reply_to = reply_to or self.endpoint
        msg.expiration_time = expiration_time or (time.time() + 10)
        msg.protocol_type = self.protocol_type
        msg.protocol_id = self.protocol_id
        msg.message_id = str(uuid.uuid1())

        shard = self.agent.descriptor.shard
        self.agent._messaging.publish(key, shard, msg)
        return d

    def reply(self, msg, reply_to, original_msg):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        dest = recipient.IRecipient(original_msg)

        msg.reply_to = recipient.IRecipient(reply_to)
        msg.message_id = str(uuid.uuid1())
        msg.protocol_id = original_msg.protocol_id
        msg.expiration_time = time.time() + 10
        msg.protocol_type = original_msg.protocol_type
        msg.session_id = original_msg.session_id

        self.agent._messaging.publish(dest.key, dest.shard, msg)
        return d

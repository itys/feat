#-*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import defer
from zope.interface import implements

from feat.common import journal, fiber, serialization
from feat.interface.journal import *
from feat.interface.serialization import *

from . import common
from feat.interface.fiber import TriggerType


class BasicRecordingDummy(journal.Recorder):

    @journal.recorded()
    def spam(self, accompaniment, extra=None):
        extra = extra and " with " + extra or ""
        return "spam and " + accompaniment + extra

    @journal.recorded("bacon")
    def async_spam(self, accompaniment, extra=None):
        extra = extra and " with " + extra or ""
        result = "spam and " + accompaniment + extra
        f = fiber.Fiber()
        f.add_callback(common.break_chain)
        f.succeed(result)
        return f


class FiberInfoDummy(journal.Recorder):

    def __init__(self, parent, async=False):
        journal.Recorder.__init__(self, parent)
        self.async = async

    def mk_fiber(self, *args):
        f = fiber.Fiber()
        for a in args:
            if self.async:
                f.add_callback(common.break_chain)
            f.add_callback(a)
        return f.succeed()

    @journal.recorded()
    def test(self, _):
        return self.mk_fiber(self.fun1a, self.fun1b)

    @journal.recorded()
    def fun1a(self, _):
        return self.mk_fiber(self.fun2a, self.fun2b)

    @journal.recorded()
    def fun1b(self, _):
        return self.mk_fiber(self.fun2a, self.fun2b)

    @journal.recorded()
    def fun2a(self, _):
        return self.mk_fiber(self.fun3, self.fun3)

    @journal.recorded()
    def fun2b(self, _):
        return self.mk_fiber(self.fun3, self.fun3)

    @journal.recorded()
    def fun3(self, _):
        pass


class NestedRecordedDummy(journal.Recorder):

    @journal.recorded()
    def main(self, a, b):
        return self.funA(a, b) + self.funB(a, b)

    @journal.recorded()
    def funA(self, a, b):
        return self.funC(a, b) + self.funD(a, b)

    @journal.recorded()
    def funB(self, a, b):
        return self.funD(a, b) + self.funD(a, b)

    @journal.recorded()
    def funC(self, a, b):
        return self.funD(a, b) + 7

    @journal.recorded()
    def funD(self, a, b):
        return a + b


class DirectReplayDummy(journal.Recorder):

    def __init__(self, parent):
        journal.Recorder.__init__(self, parent)
        self.some_foo = 0
        self.some_bar = 0
        self.some_baz = 0

    @journal.recorded()
    def foo(self, value):
        self.some_foo += value
        return self.some_foo

    @journal.recorded()
    def bar(self, value, minus=0):
        self.some_bar += value - minus
        return self.some_bar

    @journal.recorded()
    def barr(self, minus=0):
        self.some_bar -= minus
        return self.some_bar

    @journal.recorded()
    def baz(self, value):

        def async_add(v):
            self.some_baz += v
            return self.some_baz

        f = fiber.Fiber()
        f.add_callback(async_add)
        f.succeed(value)
        return f

    @journal.recorded()
    def bazz(self, value):
        '''To test second level'''
        return self.baz(value)


class RecordReplayDummy(journal.Recorder):

    def __init__(self, parent):
        journal.Recorder.__init__(self, parent)
        self.reset()

    def reset(self):
        self.servings = []

    def snapshot(self):
        return self.servings

    @journal.recorded()
    def spam(self, accompaniment, extra=None):
        extra = extra and " with " + extra or ""
        serving = "spam and %s%s" % (accompaniment, extra)
        return self._addServing(serving)

    @journal.recorded()
    def double_bacon(self, accompaniment):
        serving = "bacon and %s" % accompaniment
        self._addServing(serving)
        f = fiber.Fiber()
        f.add_callback(self.spam, extra=accompaniment)
        f.add_callback(self._prepare_double, serving)
        f.succeed("bacon")
        return f

    @journal.recorded()
    def _addServing(self, serving):
        '''Normally called only by other recorded functions'''
        self.servings.append(serving)
        return serving

    def _prepare_double(self, second_serving, first_serving):
        """Should not modify state, because it's not journalled"""
        return first_serving + " followed by " + second_serving


class ReentrantDummy(journal.Recorder):

    @journal.recorded()
    def good(self):
        return "the good, " + self.bad()

    @journal.recorded()
    def bad(self):
        return "the bad and " + self.ugly()

    @journal.recorded(reentrant=False)
    def ugly(self):
        return "the ugly"

    @journal.recorded(reentrant=False)
    def async_ugly(self):
        f = fiber.Fiber()
        f.add_callback(common.break_chain)
        f.add_callback(self.ugly)
        return f.succeed()


class ErrorDummy(journal.Recorder):

    @journal.recorded()
    def foo(self):
        return "foo"

    @journal.recorded()
    def bar(self):
        return "bar"

    @journal.recorded("baz")
    def barr(self):
        return "barr"

    @journal.recorded()
    def bad(self):
        return defer.succeed(None)

    @journal.recorded()
    def super_bad(self):
        return self.bad()


try:

    class DuplicatedErrorDummy1(journal.Recorder):

        @journal.recorded()
        def spam(self):
            pass

        @journal.recorded()
        def spam(self):
            pass

        duplicated_function_error1 = False

except RuntimeError:
    duplicated_function_error1 = True


try:

    class DuplicatedErrorDummy2(journal.Recorder):

        @journal.recorded("foo")
        def spam(self):
            pass

        @journal.recorded("foo")
        def bacon(self):
            pass

        duplicated_function_error2 = False

except RuntimeError:
    duplicated_function_error2 = True


# Used to inspect what side-effect code got really called
_effect_calls = []


@journal.side_effect
def spam_effect(accomp, extra=None):
    global _effect_calls
    _effect_calls.append("spam_effect")
    extra_desc = extra and (" with " + extra) or ""
    return ("spam and %s%s followed by %s"
            % (accomp, extra_desc, bacon_effect("spam", extra=extra)))


@journal.side_effect
def bacon_effect(accomp, extra=None):
    global _effect_calls
    _effect_calls.append("bacon_effect")
    extra_desc = extra and (" with " + extra) or ""
    return "bacon and %s%s" % (accomp, extra_desc)


def fun_without_effect(obj):
    global _effect_calls
    _effect_calls.append("fun_without_effect")
    return fun_with_effect(obj)


@journal.side_effect
def fun_with_effect(obj):
    global _effect_calls
    _effect_calls.append("fun_with_effect")
    return obj.meth_without_effect()


@journal.side_effect
def bad_effect1():
    return defer.succeed(None)


@journal.side_effect
def bad_effect2():
    f = fiber.Fiber()
    f.succeed(None)
    return f


@journal.side_effect
def bad_effect3():
    return bad_effect1()


def bad_effect4():
    return bad_effect2()


@journal.side_effect
def bad_replay_effect(*args, **kwargs):
    return "ok"


class SideEffectsDummy(object):

    def __init__(self, name):
        self.name = name

    @journal.side_effect
    def beans_effect(self, accomp, extra=None):
        global _effect_calls
        _effect_calls.append("beans_effect")
        extra_desc = extra and (" with " + extra) or ""
        return ("%s beans and %s%s followed by %s"
                % (self.name, accomp, extra_desc,
                   self.eggs_effect("spam", extra=extra)))

    @journal.side_effect
    def eggs_effect(self, accomp, extra=None):
        global _effect_calls
        _effect_calls.append("eggs_effect")
        extra_desc = extra and (" with " + extra) or ""
        return "%s eggs and %s%s" % (self.name, accomp, extra_desc)

    @journal.side_effect
    def test_effect(self):
        global _effect_calls
        _effect_calls.append("test_effect")
        return fun_without_effect(self)

    def meth_without_effect(self):
        global _effect_calls
        _effect_calls.append("meth_without_effect")
        return self.meth_with_effect()

    @journal.side_effect
    def meth_with_effect(self):
        global _effect_calls
        _effect_calls.append("meth_with_effect")
        return "ok"


class A(journal.Recorder):

    @journal.recorded()
    def foo(self):
        return "A.foo"

    def bar(self):
        return "A.bar"


class B(A):

    @journal.recorded()
    def foo(self):
        return "B.foo+" + A.foo(self)

    @journal.recorded()
    def bar(self):
        return "B.bar+" + A.bar(self)


class C(A):

    @journal.recorded()
    def foo(self):
        return "C.foo+" + A.foo(self)

    @journal.recorded()
    def bar(self):
        return "C.bar+" + A.bar(self)


class TestJournaling(common.TestCase):

    def testInheritence(self):
        K = journal.InMemoryJournalKeeper()
        R = journal.RecorderRoot(K, base_id="test")
        a = A(R)
        b = B(R)
        c = C(R)

        d = defer.succeed(None)

        d = self.assertAsyncEqual(d, "A.foo", a.foo)
        d = self.assertAsyncEqual(d, "B.foo+A.foo", b.foo)
        d = self.assertAsyncEqual(d, "C.foo+A.foo", c.foo)

        d = self.assertAsyncEqual(d, "A.bar", a.bar)
        d = self.assertAsyncEqual(d, "B.bar+A.bar", b.bar)
        d = self.assertAsyncEqual(d, "C.bar+A.bar", c.bar)

        return d

    def testJournalId(self):
        K = journal.InMemoryJournalKeeper()
        R = journal.RecorderRoot(K, base_id="test")
        A = journal.Recorder(R)
        self.assertEqual(A.journal_id, ("test", 1))
        B = journal.Recorder(R)
        self.assertEqual(B.journal_id, ("test", 2))
        AA = journal.Recorder(A)
        self.assertEqual(AA.journal_id, ("test", 1, 1))
        AB = journal.Recorder(A)
        self.assertEqual(AB.journal_id, ("test", 1, 2))
        ABA = journal.Recorder(AB)
        self.assertEqual(ABA.journal_id, ("test", 1, 2, 1))
        BA = journal.Recorder(B)
        self.assertEqual(BA.journal_id, ("test", 2, 1))

        R = journal.RecorderRoot(K)
        A = journal.Recorder(R)
        self.assertEqual(A.journal_id, (1, ))
        B = journal.Recorder(R)
        self.assertEqual(B.journal_id, (2, ))
        AA = journal.Recorder(A)
        self.assertEqual(AA.journal_id, (1, 1))

    def testBasicRecording(self):

        def check_records(_, records):
            # Filter out the fiber related fields
            records = [r[:2] + r[4:] for r in records]
            # instance_id should be the same
            iid = records[0][0]

            spam_id = "feat.test.test_common_journal.BasicRecordingDummy.spam"
            bacon_id = "bacon"

            break_call = (('feat.test.common.break_chain', None, None), None)

            expected = [(iid, spam_id, (("beans", ), None),
                         None, "spam and beans"),

                        (iid, spam_id, (("beans", ), {"extra": "spam"}),
                         None, "spam and beans with spam"),

                        (iid, bacon_id, (("beans", ), None),
                         None, (TriggerType.succeed,
                                "spam and beans",
                                [break_call])),

                        (iid, bacon_id, (("beans", ), {"extra": "spam"}),
                         None, (TriggerType.succeed,
                                "spam and beans with spam",
                                [break_call]))]

            self.assertEqual(expected, records)

        keeper = journal.InMemoryJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = BasicRecordingDummy(root)
        self.assertEqual(obj, keeper.lookup(obj.journal_id))
        d = self.assertAsyncEqual(None, "spam and beans",
                                  obj.spam, "beans")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.spam, "beans", extra="spam")
        d = self.assertAsyncEqual(d, "spam and beans",
                                  obj.async_spam, "beans")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  obj.async_spam, "beans", extra="spam")
        return d.addCallback(check_records, keeper.get_records())

    def testFiberInfo(self):

        def check_fid_and_filter(records):
            fid = records[0][1]
            for record in records:
                self.assertEqual(fid, record[1])
            return fid, [(r[0], r[2]) for r in records]

        def check_records(_, records):

            test_id = "feat.test.test_common_journal.FiberInfoDummy.test"
            fun1a_id = "feat.test.test_common_journal.FiberInfoDummy.fun1a"
            fun1b_id = "feat.test.test_common_journal.FiberInfoDummy.fun1b"
            fun2a_id = "feat.test.test_common_journal.FiberInfoDummy.fun2a"
            fun2b_id = "feat.test.test_common_journal.FiberInfoDummy.fun2b"
            fun3_id = "feat.test.test_common_journal.FiberInfoDummy.fun3"

            records = [r[1:4] for r in records]

            # Used to ensure all fibers have different identifier
            fids = set()

            # obj.fun3, only one entry
            entries, records = records[:1], records[1:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(fun3_id, 0)], entries)

            # obj.fun2a, 3 entries
            entries, records = records[:3], records[3:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(fun2a_id, 0), (fun3_id, 1),
                              (fun3_id, 1)], entries)

            # obj.fun1a, 7 entries
            entries, records = records[:7], records[7:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(fun1a_id, 0),
                              (fun2a_id, 1), (fun3_id, 2), (fun3_id, 2),
                              (fun2b_id, 1), (fun3_id, 2),
                              (fun3_id, 2)], entries)

            # obj.test, 15 entries
            entries, records = records[:15], records[15:]
            fid, entries = check_fid_and_filter(entries)
            self.assertFalse(fid in fids)
            fids.add(fid)
            self.assertEqual([(test_id, 0),
                              (fun1a_id, 1),
                              (fun2a_id, 2), (fun3_id, 3), (fun3_id, 3),
                              (fun2b_id, 2), (fun3_id, 3), (fun3_id, 3),
                              (fun1b_id, 1),
                              (fun2a_id, 2), (fun3_id, 3), (fun3_id, 3),
                              (fun2b_id, 2), (fun3_id, 3),
                              (fun3_id, 3)], entries)

        d = defer.succeed(None)

        # Test with "synchronous" fibers where callbacks are called right away
        keeper = journal.InMemoryJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = FiberInfoDummy(root, False)
        d.addCallback(obj.fun3)
        d.addCallback(obj.fun2a)
        d.addCallback(obj.fun1a)
        d.addCallback(obj.test)
        d.addCallback(check_records, keeper.get_records())

        # test with "real" asynchronous fibers
        keeper = journal.InMemoryJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = FiberInfoDummy(root, True)
        d.addCallback(obj.fun3)
        d.addCallback(obj.fun2a)
        d.addCallback(obj.fun1a)
        d.addCallback(obj.test)
        d.addCallback(check_records, keeper.get_records())

        return d

    def testNestedRecordedFunction(self):

        def drop_result(_, fun, *args, **kwargs):
            return fun(*args, **kwargs)

        def check_records(_, records):
            self.assertEqual(5, len(records))
            expected = [39, # ((3 + 5) + 7) + (3 + 5)) + ((3 + 5) + (3 + 5))
                        23, # ((3 + 5) + 7) + (3 + 5)
                        16, # (3 + 5) + (3 + 5)
                        15, # (3 + 5) + 7
                         8] # 3 + 5
            self.assertEqual(expected, [r[6] for r in records]),

        keeper = journal.InMemoryJournalKeeper()
        root = journal.RecorderRoot(keeper)
        obj = NestedRecordedDummy(root)

        d = defer.succeed(None)
        d.addCallback(drop_result, obj.main, 3, 5)
        d.addCallback(drop_result, obj.funA, 3, 5)
        d.addCallback(drop_result, obj.funB, 3, 5)
        d.addCallback(drop_result, obj.funC, 3, 5)
        d.addCallback(drop_result, obj.funD, 3, 5)
        d.addCallback(check_records, keeper.get_records())

        return d

    def testDirectReplay(self):

        foo_id = "feat.test.test_common_journal.DirectReplayDummy.foo"
        bar_id = "feat.test.test_common_journal.DirectReplayDummy.bar"
        barr_id = "feat.test.test_common_journal.DirectReplayDummy.barr"
        baz_id = "feat.test.test_common_journal.DirectReplayDummy.baz"
        bazz_id = "feat.test.test_common_journal.DirectReplayDummy.bazz"

        def snapshot(result):
            side_effects, output = result
            return (ISnapshotable(side_effects).snapshot(),
                    ISnapshotable(output).snapshot())

        k = journal.InMemoryJournalKeeper()
        r = journal.RecorderRoot(k)
        o = DirectReplayDummy(r)
        self.assertEqual(o.some_foo, 0)
        self.assertEqual(o.some_bar, 0)
        self.assertEqual(o.some_baz, 0)

        self.assertEqual((None, 3), o.replay(foo_id, ((3, ), {})))
        self.assertEqual(3, o.some_foo)
        self.assertEqual((None, 6), o.replay(foo_id, ((3, ), None)))
        self.assertEqual(6, o.some_foo)

        self.assertEqual((None, 2), o.replay(bar_id, ((2, ), {})))
        self.assertEqual(2, o.some_bar)
        self.assertEqual((None, 4), o.replay(bar_id, ((2, ), None)))
        self.assertEqual(4, o.some_bar)
        self.assertEqual((None, 5), o.replay(bar_id, ((2, ), {"minus": 1})))
        self.assertEqual(5, o.some_bar)
        self.assertEqual((None, 3), o.replay(barr_id, ((), {"minus": 2})))
        self.assertEqual(3, o.some_bar)
        self.assertEqual((None, 2), o.replay(barr_id, (None, {"minus": 1})))
        self.assertEqual(2, o.some_bar)

        # Test that fibers are not executed
        self.assertEqual((None, (TriggerType.succeed, 5,
                                 [(("feat.test.test_common_journal.async_add",
                                    None, None),
                                   None)])),
                         snapshot(o.replay(baz_id, ((5, ), None))))
        self.assertEqual(0, o.some_baz)
        self.assertEqual((None, (TriggerType.succeed, 8,
                                 [(("feat.test.test_common_journal.async_add",
                                    None, None),
                                   None)])),
                         snapshot(o.replay(baz_id, ((8, ), None))))
        self.assertEqual(0, o.some_baz)
        self.assertEqual((None, (TriggerType.succeed, 5,
                                 [(("feat.test.test_common_journal.async_add",
                                    None, None),
                                   None)])),
                         snapshot(o.replay(bazz_id, ((5, ), None))))
        self.assertEqual(0, o.some_baz)
        self.assertEqual((None, (TriggerType.succeed, 8,
                                 [(("feat.test.test_common_journal.async_add",
                                    None, None),
                                   None)])),
                         snapshot(o.replay(bazz_id, ((8, ), None))))
        self.assertEqual(0, o.some_baz)

    def testRecordReplay(self):

        def replay(_, keeper):
            # Keep objects states and reset before replaying
            states = {}
            for obj in keeper.iter_recorders():
                states[obj.journal_id] = obj.snapshot()
                obj.reset()

            # Replaying
            for record in keeper.get_records():
                jid, fid, _, _, input, exp_side_effects, exp_output = record
                obj = keeper.lookup(jid)
                self.assertTrue(obj is not None)
                side_effects, output = obj.replay(fid, input)
                self.assertEqual(exp_side_effects,
                                 ISnapshotable(side_effects).snapshot())
                self.assertEqual(exp_output,
                                 ISnapshotable(output).snapshot())

            # Check the objects state are the same after replay
            for obj in keeper.iter_recorders():
                self.assertEqual(states[obj.journal_id], obj.snapshot())

        k = journal.InMemoryJournalKeeper()
        r = journal.RecorderRoot(k)
        o1 = RecordReplayDummy(r)
        o2 = RecordReplayDummy(r)

        d = self.assertAsyncEqual(None, "spam and beans",
                                  o1.spam, "beans")
        d = self.assertAsyncEqual(d, "spam and spam",
                                  o2.spam, "spam")
        d = self.assertAsyncEqual(d, "spam and beans with spam",
                                  o1.spam, "beans", extra="spam")
        d = self.assertAsyncEqual(d, "spam and spam with spam",
                                  o2.spam, "spam", extra="spam")
        d = self.assertAsyncEqual(d, "bacon and eggs followed by "
                                  "spam and bacon with eggs",
                                  o1.double_bacon, "eggs")
        d = self.assertAsyncEqual(d, "bacon and spam followed by "
                                  "spam and bacon with spam",
                                  o2.double_bacon, "spam")
        d = self.assertAsyncEqual(d, ["spam and beans",
                                      "spam and beans with spam",
                                      "bacon and eggs",
                                      "spam and bacon with eggs"],
                                  o1.servings)
        d = self.assertAsyncEqual(d, ["spam and spam",
                                      "spam and spam with spam",
                                      "bacon and spam",
                                      "spam and bacon with spam"],
                                  o2.servings)
        d.addCallback(replay, k)

        return d

    def testNonReentrant(self):
        k = journal.InMemoryJournalKeeper()
        r = journal.RecorderRoot(k)
        o = ReentrantDummy(r)

        self.assertRaises(ReentrantCallError, o.good)
        self.assertRaises(ReentrantCallError, o.bad)

        d = self.assertAsyncEqual(None, "the ugly", o.ugly)
        d = self.assertAsyncFailure(d, [ReentrantCallError], o.async_ugly)

        return d

    def testErrors(self):
        # Check initialization errors
        self.assertTrue(duplicated_function_error1)
        self.assertTrue(duplicated_function_error2)

        k = journal.InMemoryJournalKeeper()
        r = journal.RecorderRoot(k)
        o = ErrorDummy(r)

        wrong1_id = "feat.test.test_common_journal.ErrorDummy.spam"
        wrong2_id = "feat.test.test_common_journal.ErrorDummy.barr"

        foo_id = "feat.test.test_common_journal.ErrorDummy.foo"
        bar_id = "feat.test.test_common_journal.ErrorDummy.bar"
        barr_id = "baz" # Customized ID
        bad_id = "feat.test.test_common_journal.ErrorDummy.bad"
        super_bad_id = "feat.test.test_common_journal.ErrorDummy.super_bad"

        # Recording with wrong function identifier
        self.assertRaises(AttributeError, o.record, wrong1_id)
        self.assertRaises(AttributeError, o.record, wrong2_id)

        # Calling wrong function

        def wrong_fun():
            pass

        self.assertRaises(AttributeError, o.call, wrong_fun)

        # Replaying with wrong function identifier
        self.assertRaises(AttributeError, o.replay, wrong1_id, (None, None))
        self.assertRaises(AttributeError, o.replay, wrong2_id, (None, None))

        self.assertRaises(RecordingResultError, o.bad)
        self.assertRaises(RecordingResultError, o.super_bad)

        self.assertRaises(RecordingResultError, o.record, bad_id)
        self.assertRaises(RecordingResultError, o.record, super_bad_id)

        d = self.assertAsyncEqual(None, "foo", o.record, foo_id)
        d = self.assertAsyncEqual(d, "bar", o.record, bar_id)
        d = self.assertAsyncEqual(d, "barr", o.record, barr_id)

        d = self.assertAsyncEqual(d, (None, "foo"),
                                  o.replay, foo_id, (None, None))
        d = self.assertAsyncEqual(d, (None, "bar"),
                                  o.replay, bar_id, (None, None))
        d = self.assertAsyncEqual(d, (None, "barr"),
                                  o.replay, barr_id, (None, None))

        return d

    def testSideEffectsErrors(self):
        # Tests outside recording context
        self.assertRaises(SideEffectResultError, bad_effect1)
        self.assertRaises(SideEffectResultError, bad_effect2)
        self.assertRaises(SideEffectResultError, bad_effect3)
        self.assertRaises(SideEffectResultError, bad_effect4)

        # Setup a recording environment
        section = fiber.WovenSection()
        section.enter()
        side_effects = []
        section.state[journal.RECORDED_TAG] = JournalMode.recording
        section.state[journal.SIDE_EFFECTS_TAG] = side_effects

        self.assertRaises(SideEffectResultError, bad_effect1)
        self.assertRaises(SideEffectResultError, bad_effect2)
        self.assertRaises(SideEffectResultError, bad_effect3)
        self.assertRaises(SideEffectResultError, bad_effect4)

        section.abort()

        # Setup a replay environment
        section = fiber.WovenSection()
        section.enter()
        funid = "feat.test.test_common_journal.bad_replay_effect"
        side_effects = ([(funid, (42, 18), None, "ok"),
                         (funid, None, {"extra": "foo"}, "ok"),
                         (funid, (42, 18), {"extra": "foo"}, "ok")]
                        + [(funid, None, None, "ok")] * 4)
        section.state[journal.RECORDED_TAG] = JournalMode.replay
        section.state[journal.SIDE_EFFECTS_TAG] = side_effects

        self.assertEqual("ok", bad_replay_effect(42, 18))
        self.assertEqual("ok", bad_replay_effect(extra="foo"))
        self.assertEqual("ok", bad_replay_effect(42, 18, extra="foo"))
        self.assertEqual("ok", bad_replay_effect())
        self.assertRaises(ReplayError, bad_replay_effect, 42)
        self.assertRaises(ReplayError, bad_replay_effect, extra=18)
        self.assertRaises(ReplayError, bad_effect1)
        self.assertRaises(ReplayError, bad_replay_effect)

        section.abort()

    def testSideEffectsFunctionCalls(self):
        global _effect_calls
        _effect_calls = []
        spam_effect_id = "feat.test.test_common_journal.spam_effect"
        bacon_effect_id = "feat.test.test_common_journal.bacon_effect"

        # Tests outside recording context
        del _effect_calls[:]
        self.assertEqual(bacon_effect("eggs", extra="spam"),
                         "bacon and eggs with spam")
        self.assertEqual(_effect_calls, ["bacon_effect"])

        del _effect_calls[:]
        self.assertEqual(spam_effect("spam", extra="beans"),
                         "spam and spam with beans followed by "
                         "bacon and spam with beans")
        self.assertEqual(_effect_calls, ["spam_effect", "bacon_effect"])

        # Tests inside recording context
        section = fiber.WovenSection()
        section.enter()
        side_effects = []
        replay_side_effects = []
        section.state[journal.RECORDED_TAG] = JournalMode.recording
        section.state[journal.SIDE_EFFECTS_TAG] = side_effects

        del _effect_calls[:]
        del side_effects[:]
        self.assertEqual(bacon_effect("spam", extra="eggs"),
                         "bacon and spam with eggs")
        self.assertEqual(_effect_calls, ["bacon_effect"])
        self.assertEqual(side_effects,
                         [(bacon_effect_id, ("spam", ), {"extra": "eggs"},
                           "bacon and spam with eggs")])
        replay_side_effects.extend(side_effects) # Keep for later replay

        del _effect_calls[:]
        del side_effects[:]
        self.assertEqual(spam_effect("beans", extra="spam"),
                         "spam and beans with spam followed by "
                         "bacon and spam with spam")
        self.assertEqual(_effect_calls, ["spam_effect", "bacon_effect"])
        self.assertEqual(side_effects,
                         [(spam_effect_id, ("beans", ), {"extra": "spam"},
                           "spam and beans with spam followed by "
                           "bacon and spam with spam")])
        replay_side_effects.extend(side_effects) # Keep for later replay

        section.abort()

        # Test in replay context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECORDED_TAG] = JournalMode.replay
        section.state[journal.SIDE_EFFECTS_TAG] = replay_side_effects

        del _effect_calls[:]
        self.assertEqual(bacon_effect("spam", extra="eggs"),
                         "bacon and spam with eggs")
        self.assertEqual(_effect_calls, []) # Nothing got called

        del _effect_calls[:]
        self.assertEqual(spam_effect("beans", extra="spam"),
                         "spam and beans with spam followed by "
                         "bacon and spam with spam")
        self.assertEqual(_effect_calls, []) # Nothing got called

        section.abort()

    def testSideEffectsMethodCalls(self):
        global _effect_calls
        _effect_calls = []
        beans_effect_id = "feat.test.test_common_journal." \
                          "SideEffectsDummy.beans_effect"
        eggs_effect_id = "feat.test.test_common_journal." \
                         "SideEffectsDummy.eggs_effect"

        obj = SideEffectsDummy("chef's")

        # Tests outside recording context
        del _effect_calls[:]
        self.assertEqual(obj.eggs_effect("spam", extra="bacon"),
                         "chef's eggs and spam with bacon")
        self.assertEqual(_effect_calls, ["eggs_effect"])

        del _effect_calls[:]
        self.assertEqual(obj.beans_effect("spam", extra="eggs"),
                         "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")
        self.assertEqual(_effect_calls, ["beans_effect", "eggs_effect"])

        # Tests inside recording context
        section = fiber.WovenSection()
        section.enter()
        side_effects = []
        replay_side_effects = []
        section.state[journal.RECORDED_TAG] = JournalMode.recording
        section.state[journal.SIDE_EFFECTS_TAG] = side_effects

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual(obj.eggs_effect("spam", extra="bacon"),
                         "chef's eggs and spam with bacon")
        self.assertEqual(_effect_calls, ["eggs_effect"])
        self.assertEqual(side_effects,
                         [(eggs_effect_id, ("spam", ), {"extra": "bacon"},
                           "chef's eggs and spam with bacon")])
        replay_side_effects.extend(side_effects) # Keep for later replay

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual(obj.beans_effect("spam", extra="eggs"),
                         "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")
        self.assertEqual(_effect_calls, ["beans_effect", "eggs_effect"])
        self.assertEqual(side_effects,
                         [(beans_effect_id, ("spam", ), {"extra": "eggs"},
                           "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")])
        replay_side_effects.extend(side_effects) # Keep for later replay

        section.abort()

        # Test in replay context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECORDED_TAG] = JournalMode.replay
        section.state[journal.SIDE_EFFECTS_TAG] = replay_side_effects

        del _effect_calls[:]
        self.assertEqual(obj.eggs_effect("spam", extra="bacon"),
                         "chef's eggs and spam with bacon")
        self.assertEqual(_effect_calls, []) # Nothing got called

        del _effect_calls[:]
        self.assertEqual(obj.beans_effect("spam", extra="eggs"),
                         "chef's beans and spam with eggs followed by "
                         "chef's eggs and spam with eggs")
        self.assertEqual(_effect_calls, []) # Nothing got called

        section.abort()

    def testCallChain(self):
        global _effect_calls
        _effect_calls = []
        fun_with_id = "feat.test.test_common_journal.fun_with_effect"
        fun_without_id = "feat.test.test_common_journal.fun_without_effect"
        meth_test_id = "feat.test.test_common_journal." \
                       "SideEffectsDummy.test_effect"
        meth_with_id = "feat.test.test_common_journal." \
                       "SideEffectsDummy.meth_with_effect"
        meth_without_id = "feat.test.test_common_journal." \
                          "SideEffectsDummy.meth_without_effect"

        obj = SideEffectsDummy("dummy")

        # test outside of any reocrding context

        del _effect_calls[:]
        self.assertEqual("ok", obj.test_effect())
        self.assertEqual(["test_effect", "fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", fun_without_effect(obj))
        self.assertEqual(["fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", fun_with_effect(obj))
        self.assertEqual(["fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_without_effect())
        self.assertEqual(["meth_without_effect",
                          "meth_with_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_with_effect())
        self.assertEqual(["meth_with_effect"], _effect_calls)

        # Test from inside a recording context
        section = fiber.WovenSection()
        section.enter()
        side_effects = []
        replay_side_effects = []
        section.state[journal.RECORDED_TAG] = JournalMode.recording
        section.state[journal.SIDE_EFFECTS_TAG] = side_effects

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual("ok", obj.test_effect())
        self.assertEqual(["test_effect", "fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual([(meth_test_id, None, None, "ok")], side_effects)
        replay_side_effects.extend(side_effects)

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual("ok", fun_without_effect(obj))
        self.assertEqual(["fun_without_effect",
                          "fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual([(fun_with_id, (obj, ), None, "ok")], side_effects)
        replay_side_effects.extend(side_effects)

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual("ok", fun_with_effect(obj))
        self.assertEqual(["fun_with_effect", "meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual([(fun_with_id, (obj, ), None, "ok")], side_effects)
        replay_side_effects.extend(side_effects)

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_without_effect())
        self.assertEqual(["meth_without_effect",
                          "meth_with_effect"], _effect_calls)
        self.assertEqual([(meth_with_id, None, None, "ok")], side_effects)
        replay_side_effects.extend(side_effects)

        del side_effects[:]
        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_with_effect())
        self.assertEqual(["meth_with_effect"], _effect_calls)
        self.assertEqual([(meth_with_id, None, None, "ok")], side_effects)
        replay_side_effects.extend(side_effects)

        section.abort()

        # Test from inside a replay context
        # Test from inside a recording context
        section = fiber.WovenSection()
        section.enter()
        section.state[journal.RECORDED_TAG] = JournalMode.replay
        section.state[journal.SIDE_EFFECTS_TAG] = replay_side_effects

        del _effect_calls[:]
        self.assertEqual("ok", obj.test_effect())
        self.assertEqual([], _effect_calls) # Nothing called

        del _effect_calls[:]
        self.assertEqual("ok", fun_without_effect(obj))
        self.assertEqual(["fun_without_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", fun_with_effect(obj))
        self.assertEqual([], _effect_calls) # Nothing called

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_without_effect())
        self.assertEqual(["meth_without_effect"], _effect_calls)

        del _effect_calls[:]
        self.assertEqual("ok", obj.meth_with_effect())
        self.assertEqual([], _effect_calls) # Nothing called

        section.abort()

    def testSerialization(self):
        keeper = journal.InMemoryJournalKeeper()
        root = journal.RecorderRoot(keeper, "dummy")
        obj = BasicRecordingDummy(root)
        sub = BasicRecordingDummy(obj)

        root2 = journal.RecorderRoot.restore(root.snapshot())
        self.assertEqual(root.journal_keeper, root2.journal_keeper)
        # Check that the identifier generator has not been reset
        self.assertNotEqual(obj.journal_id,
                            BasicRecordingDummy(root2).journal_id)

        obj2 = BasicRecordingDummy.restore(obj.snapshot())
        self.assertEqual(obj.journal_keeper, obj2.journal_keeper)
        self.assertEqual(obj.journal_parent, obj2.journal_parent)
        self.assertEqual(obj.journal_id, obj2.journal_id)
        # Check that the identifier generator has not been reset
        self.assertNotEqual(sub.journal_id,
                            BasicRecordingDummy(obj2).journal_id)

from twisted.python import failure

from feat.agencies import retrying
from feat.agents.base import descriptor, replay, task, partners, dependency
from feat.common import enum, fiber, formatable, serialization

# To access from this module
from feat.agents.monitor.interface import RestartStrategy
from feat.agents.monitor.interface import RestartFailed, MonitoringFailed
from feat.agents.monitor.interface import IPacemakerFactory, IPacemaker
from feat.agents.monitor.pacemaker import Pacemaker, FakePacemaker

from feat.interface.agency import *


__all__ = ['notify_restart_complete',
           'Descriptor', 'RestartFailed', 'RestartStrategy',
           'PartnerMixin', 'AgentMixin',
           'IPacemakerFactory', 'IPacemaker',
           'Pacemaker', 'FakePacemaker', "PendingNotification"]


def notify_restart_complete(agent, monitor, recp):
    '''
    Use this for finalizing custom restart procedure of some agent. If
    his partner accepted responsibility in on_died() callback, he needs
    to notify the monitor agent the the restart procedure is complete.
    @param agent: Agent performing the restart
    @param monitor: IRecipient of the monitor agent who sent us the
                    on_died() notification
    @param recp: IRecipient of the agent who died and got restarted.
    '''
    return agent.call_remote(monitor, 'restart_complete', recp)


def discover(agent, shard=None):
    shard = shard or agent.get_own_address().shard
    return agent.discover_service("monitoring", timeout=1, shard=shard)


class PartnerMixin(object):
    '''When used as a base class for a partner that do not redefine
    on_goodbye(), this class should be appear before any BasePartner subclass
    in the list of super classes. If not, the BasePartner on_goodbye() will
    be called and nothing will happen.
    See feat.agents.base.agent.BasePartner.'''

    def initiate(self, agent):
        f = agent.get_document("monitor_agent_conf")
        f.add_callback(self._start_heartbeat, agent)
        return f

    def on_goodbye(self, agent, payload):
        agent.stop_heartbeat(self.recipient)
        agent.lookup_monitor()

    def on_buried(self, agent, payload):
        agent.stop_heartbeat(self.recipient)
        agent.lookup_monitor()

    def _start_heartbeat(self, doc, agent):
        return agent.start_heartbeat(self.recipient, doc.heartbeat_period)


class AgentMixin(object):

    restart_strategy = RestartStrategy.buryme

    dependency.register(IPacemakerFactory, Pacemaker, ExecMode.production)
    dependency.register(IPacemakerFactory, FakePacemaker, ExecMode.test)
    dependency.register(IPacemakerFactory, FakePacemaker, ExecMode.simulation)

    need_local_monitoring = True

    @replay.immutable
    def startup_monitoring(self, state):
        if not state.partners.monitors:
            self.lookup_monitor()

    @replay.mutable
    def cleanup_monitoring(self, state):
        self._lazy_mixin_init()
        for pacemaker in state.pacemakers.values():
            pacemaker.cleanup()
        state.pacemakers.clear()

    @replay.mutable
    def start_heartbeat(self, state, monitor, period):
        self._lazy_mixin_init()
        pacemaker = self.dependency(IPacemakerFactory, self, monitor, period)
        pacemaker.startup()
        state.pacemakers[monitor.key] = pacemaker

    @replay.mutable
    def stop_heartbeat(self, state, monitor):
        self._lazy_mixin_init()
        if monitor.key in state.pacemakers:
            del state.pacemakers[monitor.key]

    @replay.immutable
    def lookup_monitor(self, state):
        if self.need_local_monitoring:
            Factory = retrying.RetryingProtocolFactory
            factory = Factory(SetupMonitoringTask, max_delay=60, busy=False)
            self.initiate_protocol(factory)

    ### Private Methods ###

    @replay.mutable
    def _lazy_mixin_init(self, state):
        if not hasattr(state, "pacemakers"):
            state.pacemakers = {} # {AGENT_ID: IPacemaker}


class SetupMonitoringTask(task.BaseTask):

    busy = False
    protocol_id = "setup-monitoring"

    def __init__(self, *args, **kwargs):
        task.BaseTask.__init__(self, *args, **kwargs)

    @replay.entry_point
    def initiate(self, state, shard=None):
        self.debug("Looking up a monitor for %s %s",
                   state.agent.descriptor_type, state.agent.get_full_id())
        f = fiber.Fiber(state.medium.get_canceller())
        f.add_callback(discover, shard)
        f.add_callback(self._start_monitoring)
        return f.succeed(state.agent)

    @replay.journaled
    def _start_monitoring(self, state, monitors):
        if not monitors:
            ex = MonitoringFailed("No monitor agent found in shard for %s %s"
                                  % (state.agent.descriptor_type,
                                     state.agent.get_full_id()))
            #raise ex
            return fiber.fail(ex)

        monitor = monitors[0]
        self.info("Monitor found for %s %s: %s", state.agent.descriptor_type,
                  state.agent.get_full_id(), monitor.key)
        f = state.agent.establish_partnership(monitor)
        f.add_errback(failure.Failure.trap, partners.DoublePartnership)
        return f


@descriptor.register("monitor_agent")
class Descriptor(descriptor.Descriptor):

    # agent_id -> [PendingNotification]
    formatable.field('pending_notifications', dict())


@serialization.register
class PendingNotification(formatable.Formatable):

    type_name = 'notification'

    formatable.field('type', None)
    formatable.field('origin', None)
    formatable.field('payload', None)
    formatable.field('recipient', None)

from zope.interface import implements
from feat.interface import manager
from feat.common import log
from feat.agencies import agency
from feat.agents.base import protocol, replay


class Meta(type(replay.Replayable)):
    implements(manager.IManagerFactory)


class BaseManager(log.Logger, protocol.InitiatorBase, replay.Replayable):
    """
    I am a base class for managers of contracts.

    @ivar protocol_type: the type of contract this manager manages.
                         Must match the type of the contractor for this
                         contract; see L{feat.agents.contractor.BaseContractor}
    @type protocol_type: str
    """
    __metaclass__ = Meta

    implements(manager.IAgentManager)

    announce = None
    grant = None
    report = None
    agent = None

    log_category = "manager"
    protocol_type = "Contract"
    protocol_id = None

    initiate_timeout = 10
    announce_timeout = 10
    grant_timeout = 10

    def __init__(self, agent, medium, *args, **kwargs):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium, *args, **kwargs)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    def initiate(self):
        '''@see: L{manager.IAgentManager}'''

    def bid(self, bid):
        '''@see: L{manager.IAgentManager}'''

    def closed(self):
        '''@see: L{manager.IAgentManager}'''

    def expired(self):
        '''@see: L{manager.IAgentManager}'''

    def cancelled(self, grant, cancellation):
        '''@see: L{manager.IAgentManager}'''

    def completed(self, grant, report):
        '''@see: L{manager.IAgentManager}'''

    def aborted(self, grant):
        '''@see: L{manager.IAgentManager}'''

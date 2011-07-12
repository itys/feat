import operator

from zope.interface.interface import InterfaceClass

from feat.common import annotate, reflect, container
from feat.agents.base import replay


def register(component, canonical_name, mode):
    annotate.injectClassCallback("dependency", 3, "_register_dependency",
                                 component, canonical_name, mode)


class UndefinedDependency(Exception):
    pass


class AgentDependencyMixin(object):
    '''
    Mixin for the BaseAgent to handle dependencies.
    '''

    _dependencies = container.MroDict("_mro_dependencies")

    @classmethod
    def _register_dependency(cls, component, canonical_name, mode):
        if not isinstance(component, InterfaceClass):
            raise AttributeError(
                'Component %r should be an Interface. Got %r instead.' % \
                component.__class__.__name__)

        if component not in cls._dependencies:
            cls._dependencies[component] = dict()
        cls._dependencies[component][mode] = canonical_name

    @classmethod
    def _get_dependency_for_component(cls, component):
        return cls._dependencies.get(component, None)

    @classmethod
    def _iter_dependencies(cls):
        return cls._dependencies.iteritems()

    @classmethod
    def _get_defined_components(cls):
        return cls._dependencies.keys()

    @replay.immutable
    def dependency(self, state, component, *args, **kwargs):
        mode = state.medium.get_mode(component)
        for_component = self._get_dependency_for_component(component)
        if for_component is None:
            raise UndefinedDependency(
                'Component %s is not defined. Defined components are: %r' %\
                (component, self._get_defined_components(), ))
        canonical_name = for_component.get(mode, None)

        if canonical_name is None:
            raise UndefinedDependency(
                'Component %s is not defined for the mode %r. '
                'Defined handlers are for the modes: %r' %\
                (component, mode, for_component.keys(), ))

        # What we might pass in registration is either a callable object
        # or its canonical name.
        # Here we handle lazy imports in this second case.
        if callable(canonical_name):
            calable = canonical_name
        else:
            calable = reflect.named_object(canonical_name)
        if not component.providedBy(calable):
            raise UndefinedDependency(
                'Expected object %r to provide the interface %r!' %\
                (calable, component, ))

        return calable(*args, **kwargs)

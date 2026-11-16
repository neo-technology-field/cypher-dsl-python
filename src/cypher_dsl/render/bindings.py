"""
Per-render parameter binding collection.

Bindings belong to one render, never to the syntax tree or the statement. Keeping them
here means the same tree can be rendered repeatedly, or concurrently through one
renderer, without one call observing another call's values.
"""

from __future__ import annotations

from typing import cast

from cypher_dsl.errors import ConflictingParameterError
from cypher_dsl.expressions.values import UNBOUND, FrozenValue, Unbound, same_binding, thaw_value


class BindingCollector:
    """
    Collect bound values and unbound names for one render.

    A bound occurrence resolves an unbound occurrence of the same name regardless of
    traversal order. Two different bindings for one name are a conflict and stop the
    render before any caller receives partial result data.
    """

    __slots__ = ("_bound", "_unbound")

    def __init__(self) -> None:
        """Start an empty collection."""
        self._bound: dict[str, FrozenValue] = {}
        self._unbound: set[str] = set()

    def record(self, parameter_name: str, binding: FrozenValue | Unbound) -> None:
        """
        Record one parameter occurrence.

        Args:
            parameter_name: Name used in the rendered placeholder.
            binding: Frozen binding value, or ``UNBOUND`` when the caller supplies it
                at execution time.

        Raises:
            ConflictingParameterError: If the name already carries a different binding.
        """
        if binding is UNBOUND:
            if parameter_name not in self._bound:
                self._unbound.add(parameter_name)
            return
        bound_value = cast(FrozenValue, binding)
        if parameter_name in self._bound and not same_binding(self._bound[parameter_name], bound_value):
            raise ConflictingParameterError(f"Conflicting bindings for ${parameter_name}")
        self._bound[parameter_name] = bound_value
        self._unbound.discard(parameter_name)

    @property
    def parameters(self) -> dict[str, object]:
        """
        Return a fresh dictionary of thawed bound values.

        Containers are rebuilt for each result, so a caller can mutate the dictionary or
        its list and map values without changing the syntax tree or a later render.
        """
        return {name: thaw_value(value) for name, value in self._bound.items()}

    @property
    def unbound_parameters(self) -> frozenset[str]:
        """Return the names that no occurrence in this render bound."""
        return frozenset(self._unbound)


__all__ = ["BindingCollector"]

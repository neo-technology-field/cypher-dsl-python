"""
Instance layout of every class the package defines.

The package keeps instances free of a per-instance dictionary: dataclasses declare
``slots=True`` and plain classes declare ``__slots__`` by hand. The check is behavioural,
so a base class that restores a dictionary for its subclasses is caught through the
subclasses that inherit it. Instances are allocated with ``object.__new__`` so that a
class-specific ``__new__`` cannot decide the outcome.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import is_dataclass
from enum import Enum
from weakref import ref

import pytest

import cypher_dsl


def _package_classes() -> set[type]:
    """Return every class the package defines, each exactly once."""
    found: set[type] = set()
    modules = [cypher_dsl]
    for module_info in pkgutil.walk_packages(cypher_dsl.__path__, "cypher_dsl."):
        modules.append(importlib.import_module(module_info.name))
    for module in modules:
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            if value.__module__ == "cypher_dsl" or value.__module__.startswith("cypher_dsl."):
                found.add(value)
    return found


def _checkable(cls: type) -> bool:
    """
    Return whether an instance of the class takes part in the layout check.

    Exceptions and enums are outside this layout policy: exceptions always carry a
    dictionary, and enum members are class attributes. Abstract classes are covered
    through their concrete subclasses, which inherit any dictionary a base fails to
    prevent.
    """
    if inspect.isabstract(cls):
        return False
    return not issubclass(cls, (BaseException, Enum))


_LAYOUT_CLASSES = sorted(
    (cls for cls in _package_classes() if _checkable(cls)),
    key=lambda cls: (cls.__module__, cls.__qualname__),
)


@pytest.mark.parametrize("cls", _LAYOUT_CLASSES, ids=lambda cls: f"{cls.__module__}.{cls.__qualname__}")
def test_instances_carry_no_dictionary(cls: type) -> None:
    """A per-instance dictionary would reintroduce the memory cost the layout avoids."""
    assert not hasattr(object.__new__(cls), "__dict__")


_WEAKREFERENCE_CLASSES = [cls for cls in _LAYOUT_CLASSES if is_dataclass(cls)]


@pytest.mark.parametrize("cls", _WEAKREFERENCE_CLASSES, ids=lambda cls: f"{cls.__module__}.{cls.__qualname__}")
def test_instances_accept_a_weak_reference(cls: type) -> None:
    """An instance can be the target of a weak reference."""
    instance = object.__new__(cls)
    assert ref(instance)() is instance


def test_package_classes_include_root_definitions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A class defined only in the package root is discovered."""

    class RootOnly:
        __slots__ = ()

    RootOnly.__module__ = cypher_dsl.__name__
    monkeypatch.setattr(cypher_dsl, "_LayoutRootOnly", RootOnly, raising=False)
    assert RootOnly in _package_classes()

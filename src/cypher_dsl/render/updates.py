"""Construct renderers for write clauses and their updates."""

from __future__ import annotations

from cypher_dsl.clauses.write import (
    Assignment,
    CreateClause,
    DeleteClause,
    LabelUpdate,
    MergeAction,
    MergeClause,
    RemoveClause,
    SetClause,
)
from cypher_dsl.render.context import RenderContext
from cypher_dsl.render.fragments import Fragment
from cypher_dsl.render.literals import quote_identifier
from cypher_dsl.render.rules import RuleBinding, bind


def assignment(node: Assignment, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render an assignment target, update operator and value."""
    return f"{children[0].text} {node.kind.value} {children[1].text}"


def label_update(node: LabelUpdate, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a variable followed by its labels in source order."""
    labels = ":".join(quote_identifier(label.value, context.always_escape_names) for label in node.labels)
    return f"{children[0].text}:{labels}"


def create_clause(node: CreateClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a CREATE clause with comma-separated patterns."""
    return f"CREATE {', '.join(child.text for child in children)}"


def merge_action(node: MergeAction, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render one ON CREATE or ON MATCH action and its assignments."""
    return f"{node.keyword} SET {', '.join(child.text for child in children)}"


def merge_clause(node: MergeClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a MERGE pattern followed by its actions."""
    actions = " ".join(child.text for child in children[1:])
    text = f"MERGE {children[0].text}"
    return text if not actions else f"{text} {actions}"


def set_clause(node: SetClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a SET clause with comma-separated updates."""
    return f"SET {', '.join(child.text for child in children)}"


def remove_clause(node: RemoveClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render a REMOVE clause with comma-separated targets."""
    return f"REMOVE {', '.join(child.text for child in children)}"


def delete_clause(node: DeleteClause, children: tuple[Fragment, ...], context: RenderContext) -> str:
    """Render DELETE or DETACH DELETE with comma-separated targets."""
    keyword = "DETACH DELETE" if node.detach else "DELETE"
    return f"{keyword} {', '.join(child.text for child in children)}"


def update_bindings() -> tuple[RuleBinding, ...]:
    """Return the write clause and update construct renderers."""
    return (
        bind(Assignment, assignment),
        bind(LabelUpdate, label_update),
        bind(CreateClause, create_clause),
        bind(MergeAction, merge_action),
        bind(MergeClause, merge_clause),
        bind(SetClause, set_clause),
        bind(RemoveClause, remove_clause),
        bind(DeleteClause, delete_clause),
    )


__all__ = ["update_bindings"]

"""Registered semantic rules, one per construct family."""

from cypher_dsl.statements.rules.base import (
    PatternState,
    SemanticRule,
    SemanticRules,
    check_references,
    frame_after,
    reject_reserved_redeclaration,
    reserved_name_conflict,
    semantic_rules,
    validate_clause,
    walk_clauses,
)
from cypher_dsl.statements.rules.call import CallRule
from cypher_dsl.statements.rules.flow import UnionRule, UnwindRule
from cypher_dsl.statements.rules.match import MatchRule
from cypher_dsl.statements.rules.projection import ProjectionRule
from cypher_dsl.statements.rules.writes import CreateRule, DeleteRule, MergeRule, RemoveRule, SetRule

__all__ = [
    "CallRule",
    "CreateRule",
    "DeleteRule",
    "MatchRule",
    "MergeRule",
    "PatternState",
    "ProjectionRule",
    "RemoveRule",
    "SemanticRule",
    "SemanticRules",
    "SetRule",
    "UnionRule",
    "UnwindRule",
    "check_references",
    "frame_after",
    "reject_reserved_redeclaration",
    "reserved_name_conflict",
    "semantic_rules",
    "shared_rules",
    "validate_clause",
    "walk_clauses",
]


def shared_rules() -> dict[type, SemanticRule]:
    """Assemble the registry. One rule instance per family, projections shared."""
    from cypher_dsl.clauses.call import SubqueryCallClause
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.projection import ReturnClause, WithClause
    from cypher_dsl.clauses.unwind import UnwindClause
    from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
    from cypher_dsl.statements.composition import UnionStatement

    projection = ProjectionRule()
    return {
        CreateClause: CreateRule(),
        DeleteClause: DeleteRule(),
        MatchClause: MatchRule(),
        MergeClause: MergeRule(),
        RemoveClause: RemoveRule(),
        ReturnClause: projection,
        SetClause: SetRule(),
        SubqueryCallClause: CallRule(),
        UnionStatement: UnionRule(),
        UnwindClause: UnwindRule(),
        WithClause: projection,
    }

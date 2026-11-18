"""Registered semantic rules, one per construct family."""

from typing import Any

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
from cypher_dsl.statements.rules.flow import UnionRule, UnwindRule
from cypher_dsl.statements.rules.labels import IsLabeledRule
from cypher_dsl.statements.rules.match import MatchRule
from cypher_dsl.statements.rules.path_patterns import PathPatternRule
from cypher_dsl.statements.rules.procedures import ProcedureCallRule
from cypher_dsl.statements.rules.projection import ProjectionRule
from cypher_dsl.statements.rules.subqueries import CallRule, SubqueryExpressionRule
from cypher_dsl.statements.rules.writes import CreateRule, DeleteRule, MergeRule, RemoveRule, SetRule

__all__ = [
    "CallRule",
    "CreateRule",
    "DeleteRule",
    "IsLabeledRule",
    "MatchRule",
    "MergeRule",
    "PathPatternRule",
    "PatternState",
    "ProcedureCallRule",
    "ProjectionRule",
    "RemoveRule",
    "SemanticRule",
    "SemanticRules",
    "SetRule",
    "SubqueryExpressionRule",
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


def shared_rules() -> dict[type, SemanticRule[Any]]:
    """Assemble the registry. One rule instance per family, projections shared."""
    from cypher_dsl.clauses.call import ProcedureCallClause, SubqueryCallClause
    from cypher_dsl.clauses.match import MatchClause
    from cypher_dsl.clauses.projection import ReturnClause, WithClause
    from cypher_dsl.clauses.unwind import UnwindClause
    from cypher_dsl.clauses.write import CreateClause, DeleteClause, MergeClause, RemoveClause, SetClause
    from cypher_dsl.expressions.labels import IsLabeled
    from cypher_dsl.expressions.path_patterns import PathPatternExpression
    from cypher_dsl.expressions.subqueries import CollectExpression, CountExpression, ExistsExpression
    from cypher_dsl.statements.composition import UnionStatement

    projection = ProjectionRule()
    subquery_expressions = SubqueryExpressionRule()
    return {
        CollectExpression: subquery_expressions,
        CountExpression: subquery_expressions,
        CreateClause: CreateRule(),
        DeleteClause: DeleteRule(),
        ExistsExpression: subquery_expressions,
        # The label predicate is a non-clause rule: it records a capability
        # requirement rather than frame bindings.
        IsLabeled: IsLabeledRule(),
        MatchClause: MatchRule(),
        MergeClause: MergeRule(),
        PathPatternExpression: PathPatternRule(),
        ProcedureCallClause: ProcedureCallRule(),
        RemoveClause: RemoveRule(),
        ReturnClause: projection,
        SetClause: SetRule(),
        SubqueryCallClause: CallRule(),
        UnionStatement: UnionRule(),
        UnwindClause: UnwindRule(),
        WithClause: projection,
    }

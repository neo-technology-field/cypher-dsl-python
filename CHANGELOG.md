# Changelog

## [0.1.0a1]
- first release

## [0.1.0a2]
- added `CALL { … }` subqueries through `call()` and `optional_call()`
- pretty printing

## [0.1.0a3]
- added procedure calls through `call_procedure()` and `optional_call_procedure()`
- added untyped relationship patterns
- added string predicates through `starts_with()`, `ends_with()` and `contains()`
- added label expressions through `label()` and `has_label()`, and `IS [NOT] LABELED` predicates through `is_labeled()` and `is_not_labeled()`
- added `EXISTS { … }` subquery expressions through `exists()`
- added path pattern expressions through `path_pattern()`
- added `COUNT { … }` and `COLLECT { … }` subquery expressions through `count_subquery()` and `collect_subquery()`
- a pattern that restates a bound node renders as the bare variable

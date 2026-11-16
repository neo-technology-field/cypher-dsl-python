"""
Safe text for literals, identifiers and parameter placeholders.

Everything here turns data into query text. A value never becomes a fragment of
Cypher, and an identifier is quoted structurally instead of being trusted. Inline bytes
are refused because no byte-literal syntax is claimed. Bind them through ``param()``
and pass the value to the driver unchanged.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Final

from cypher_dsl.errors import InvalidLiteralError
from cypher_dsl.expressions.values import FrozenValue, _FrozenList, _FrozenMap, validate_name

_SIMPLE_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ZONE_KEY: Final = re.compile(r"[A-Za-z][A-Za-z0-9._+-]*(?:/[A-Za-z0-9._+-]+)*")
_STRING_ESCAPES: Final = {
    "\\": "\\\\",
    "'": "\\'",
    '"': '\\"',
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}

# Cypher treats these words as keywords in identifier positions. Quoting a name that
# merely looks reserved is harmless, so the set is broad. Missing a word would turn a
# variable reference into syntax. Parameter names are exempt because the dollar sign
# already introduces a name token, and upstream leaves `$name` unquoted.
_RESERVED_IDENTIFIERS: Final = frozenset(
    """
    ACCESS ACTIVE ADMIN ADMINISTRATOR ALIAS ALIASES ALL ALL_SHORTEST_PATHS ALTER AND ANY
    ARRAY AS ASC ASCENDING ASSIGN AT AUTH AUTO BINDINGS BOOL BOOLEAN BOOSTED BOTH BREAK
    BUILT BY CALL CASCADE CASE CHANGE CIDR COLLECT COMMAND COMMANDS COMPOSITE CONCURRENT
    CONSTRAINT CONSTRAINTS CONTAINS CONTINUE COPY COUNT CREATE CSV CURRENT DATA DATABASE
    DATABASES DATE DATETIME DBMS DEALLOCATE DEFAULT DEFINED DELETE DENY DESC DESCENDING
    DESTROY DETACH DIFFERENT DISJOINT DISTINCT DRIVER DROP DRYRUN DUMP DURATION EACH EDGE
    ELEMENT ELEMENTS ELSE ENABLE ENCRYPTED END ENDS ERROR EXECUTABLE EXECUTE EXIST
    EXISTENCE EXISTS FAIL FALSE FIELDTERMINATOR FINISH FILTER FLOAT FOR FOREACH FROM
    FULLTEXT FUNCTION FUNCTIONS GRANT GRAPH GRAPHS GROUP GROUPS HEADERS HOME ID IF
    IMMUTABLE IMPERSONATE IN INDEX INDEXES INF INFINITY INSERT INT INTEGER IS JOIN KEY
    LABEL LABELS LEADING LET LIMIT LIMITROWS LIST LOAD LOCAL LOOKUP MANAGEMENT MAP MATCH
    MERGE NAME NAMES NAN NEW NEXT NFC NFD NFKC NFKD NODE NODES NODETACH NONE NORMALIZE
    NORMALIZED NOT NOTHING NOWAIT NULL OF OFFSET ON ONLY OPTION OPTIONAL OPTIONS OR ORDER
    PASSWORD PASSWORDS PATH PATHS PLAINTEXT POINT POPULATED PRIMARIES PRIMARY PRIVILEGE
    PRIVILEGES PROCEDURE PROCEDURES PROPERTIES PROPERTY PROVIDER PROVIDERS RANGE READ
    REALLOCATE REDUCE REL RELATIONSHIP RELATIONSHIPS REMOVE RENAME REPEATABLE REPLACE
    REPORT REQUIRE REQUIRED RESTRICT RETURN REVOKE ROLE ROLES ROW ROWS SCAN SCORE SEARCH
    SEC SECOND SECONDARIES SECONDARY SECONDS SEEK SERVER SERVERS SET SETTING SETTINGS
    SHORTEST SHORTEST_PATH SHOW SIGNED SINGLE SKIPROWS START STARTS STATUS STOP STRING
    SUPPORTED SUSPENDED TARGET TERMINATE TEXT THEN TIME TIMESTAMP TIMEZONE TO TOPOLOGY
    TRAIL TRAILING TRANSACTION TRANSACTIONS TRAVERSE TRIM TRUE TYPE TYPED TYPES UNION
    UNIQUE UNIQUENESS UNWIND URL USE USER USERS USING VALUE VALUES VARCHAR VECTOR VERBOSE
    VERTEX WAIT WHEN WHERE WITH WITHOUT WRITE XOR YIELD ZONE ZONED
    """.split()  # noqa: SIM905 - a word list is clearer as grouped prose than a 250-item tuple.
)


def escape_string(value: str) -> str:
    """
    Quote a string value, escaping characters that would end or split it.

    Backslash and both quote characters are escaped, as are the control characters
    Cypher has named escapes for. Other C0 controls and DEL use a Unicode escape so the
    query text never carries a raw control byte.

    Args:
        value: String to quote. An empty string becomes ``''``.

    Returns:
        The quoted literal, including its surrounding single quotes.
    """
    parts = ["'"]
    for character in value:
        escape = _STRING_ESCAPES.get(character)
        if escape is not None:
            parts.append(escape)
        elif ord(character) < 0x20 or ord(character) == 0x7F:
            parts.append(f"\\u{ord(character):04x}")
        else:
            parts.append(character)
    parts.append("'")
    return "".join(parts)


def quote_identifier(value: str, always_escape: bool = False) -> str:
    """
    Quote an identifier safely for a name position.

    Identifiers are literal names, not Cypher text. The text is quoted structurally,
    backticks are doubled, and words Cypher reserves are quoted even when their shape
    looks simple. Encoded escape sequences are refused rather than decoded: Cypher
    interprets ``\\u0060`` as a backtick, so passing it through would let a name end its
    own quoting and introduce another clause. A caller who wants the backtick character
    passes the character.

    Args:
        value: Identifier text as the caller supplied it.
        always_escape: Quote even when the plain form would be legal.

    Returns:
        The identifier, quoted or plain.

    Raises:
        InvalidIdentifierError: If the name is empty, contains a control character,
            contains an encoded escape sequence, or decodes to a control character.
    """
    return _quote_name(value, always_escape, quote_reserved=True)


def quote_parameter_name(value: str, always_escape: bool = False) -> str:
    """
    Quote a parameter name without the keyword rule.

    A parameter name follows a dollar sign, which already introduces a name token. A
    keyword such as ``data`` is therefore usable and stays unquoted, matching upstream.
    Shape checks, control rejection and encoded-escape rejection still apply.

    Args:
        value: Parameter name as the caller supplied it.
        always_escape: Quote even when the plain form would be legal.

    Returns:
        The name, quoted or plain, for use after ``$``.

    Raises:
        InvalidIdentifierError: If the name is empty, contains a control character,
            contains an encoded escape sequence, or decodes to a control character.
    """
    return _quote_name(value, always_escape, quote_reserved=False)


def quote_function_segment(value: str) -> str:
    """
    Quote one segment of a qualified function name.

    A function name is followed by an opening parenthesis, so the parser already knows
    it is a name token and keywords such as ``count``, ``id`` and ``left`` need no
    quoting. Forced escaping is deliberately not accepted here: quoting ``count``
    selects an ordinary function invocation and breaks the required ``count(*)``
    grammar, and the pinned renderer leaves function names unquoted regardless of the
    configuration. Shape checks, control rejection and encoded-escape rejection still
    apply, and an unusual segment is quoted structurally.

    Args:
        value: One dot-separated segment of a function name.

    Returns:
        The segment, quoted only when its own shape requires it.

    Raises:
        InvalidIdentifierError: If the segment is empty, contains a control character,
            contains an encoded escape sequence, or decodes to a control character.
    """
    return _quote_name(value, False, quote_reserved=False)


def _quote_name(value: str, always_escape: bool, quote_reserved: bool) -> str:
    validate_name(value)
    needs_quoting = always_escape or _SIMPLE_IDENTIFIER.fullmatch(value) is None
    if quote_reserved and value.upper() in _RESERVED_IDENTIFIERS:
        needs_quoting = True
    if needs_quoting:
        return f"`{value.replace('`', '``')}`"
    return value


def render_literal(value: FrozenValue, always_escape_names: bool = False) -> str:
    """
    Render a frozen value as an inline Cypher literal.

    Scalars are checked from the most specific type outwards so that booleans do not
    become integers and datetimes do not fall into the date branch. Temporal values use
    the constructor that matches their awareness rather than a generic string form.

    Args:
        value: Frozen value produced by the construction factories.
        always_escape_names: Whether map keys are always quoted.

    Returns:
        Inline Cypher syntax for the value.

    Raises:
        InvalidLiteralError: If the value is inline bytes, a non-finite float or a
            representation this renderer cannot produce.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not isfinite(value):
            raise InvalidLiteralError(
                f"Non-finite float {value!r} cannot be rendered as a Cypher literal. Bind it with param() instead."
            )
        return repr(value)
    if isinstance(value, str):
        return escape_string(value)
    if isinstance(value, bytes):
        raise InvalidLiteralError(
            "Inline bytes cannot be rendered because no byte-literal syntax is claimed. "
            "Bind the value with param() and pass the bytes to the driver unchanged."
        )
    if isinstance(value, datetime):
        return _render_datetime(value)
    if isinstance(value, date):
        return f"date({escape_string(value.isoformat())})"
    if isinstance(value, time):
        return _render_time(value)
    if isinstance(value, timedelta):
        return _render_duration(value)
    if isinstance(value, _FrozenList):
        return "[" + ", ".join(render_literal(item, always_escape_names) for item in value.items) + "]"
    if isinstance(value, _FrozenMap):
        entries = (
            f"{quote_identifier(key, always_escape_names)}: {render_literal(item, always_escape_names)}"
            for key, item in value.entries
        )
        return "{" + ", ".join(entries) + "}"
    raise InvalidLiteralError(f"Cannot render a frozen value of type {type(value).__name__} as a literal.")


def _render_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        return f"localdatetime({escape_string(value.isoformat())})"
    return f"datetime({escape_string(_aware_isoformat(value))})"


def _render_time(value: time) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        return f"localtime({escape_string(value.isoformat())})"
    return f"time({escape_string(_aware_isoformat(value))})"


def _aware_isoformat(value: datetime | time) -> str:
    text = value.isoformat()
    zone_key = getattr(value.tzinfo, "key", None)
    if isinstance(zone_key, str):
        if _ZONE_KEY.fullmatch(zone_key) is None:
            raise InvalidLiteralError(
                f"Zone identifier {zone_key!r} cannot be represented in a temporal literal. "
                "Use an IANA zone name such as 'Europe/Berlin'."
            )
        return f"{text}[{zone_key}]"
    return text


def _render_duration(value: timedelta) -> str:
    total_microseconds = (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
    sign = "-" if total_microseconds < 0 else ""
    remainder = abs(total_microseconds)
    hours, remainder = divmod(remainder, 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    parts = []
    if hours:
        parts.append(f"{hours}H")
    if minutes:
        parts.append(f"{minutes}M")
    if seconds or microseconds:
        if microseconds:
            fraction = f"{microseconds:06d}".rstrip("0")
            parts.append(f"{seconds}.{fraction}S")
        else:
            parts.append(f"{seconds}S")
    duration = f"{sign}PT{''.join(parts) or '0S'}"
    return f"duration({escape_string(duration)})"


__all__ = [
    "escape_string",
    "quote_function_segment",
    "quote_identifier",
    "quote_parameter_name",
    "render_literal",
]

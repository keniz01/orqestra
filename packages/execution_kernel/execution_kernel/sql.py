"""Deterministic read-only SQL validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp


class SqlValidationError(ValueError):
    """Raised when a query cannot be proven to be a safe read."""


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    sql: str
    tables: tuple[str, ...]
    columns: frozenset[str]


_FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "dblink",
    "lo_import",
    "lo_export",
}
_FORBIDDEN_TABLE_PREFIXES = ("pg_", "information_schema")
_MAX_QUERY_LENGTH = 10_000
_MULTI_STATEMENT_RE = re.compile(r";\s*\S")


def validate_read_query(sql: str, *, max_length: int = _MAX_QUERY_LENGTH) -> ValidatedQuery:
    """Parse and validate one SELECT/WITH query without repairing it."""

    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError("SQL query cannot be empty.")
    if "\x00" in sql:
        raise SqlValidationError("SQL query contains an invalid control character.")
    if len(sql) > max_length:
        raise SqlValidationError(f"SQL query exceeds the {max_length}-character limit.")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise SqlValidationError("SQL comments are not allowed.")
    if _MULTI_STATEMENT_RE.search(sql):
        raise SqlValidationError("Multiple SQL statements are not allowed.")

    try:
        statements = sqlglot.parse(sql)
    except sqlglot.errors.ParseError as exc:
        raise SqlValidationError("SQL query could not be parsed.") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SqlValidationError("Exactly one SQL statement is required.")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.With)):
        raise SqlValidationError("Only SELECT and WITH queries are allowed.")

    forbidden_functions = {
        node.name.lower()
        for node in statement.walk()
        if isinstance(node, exp.Func) and node.name
    }
    if forbidden_functions & _FORBIDDEN_FUNCTIONS:
        raise SqlValidationError("The query uses a forbidden function.")

    parsed_tables = tuple(
        table
        for table in statement.find_all(exp.Table)
        if table.name
    )
    tables = tuple(sorted({table.name.lower() for table in parsed_tables}))
    qualified_tables = tuple(
        ".".join(
            part.lower()
            for part in (table.catalog, table.db, table.name)
            if part
        )
        for table in parsed_tables
    )
    if any(
        table.startswith(_FORBIDDEN_TABLE_PREFIXES)
        or any(prefix in table.split(".") for prefix in _FORBIDDEN_TABLE_PREFIXES)
        for table in qualified_tables
    ):
        raise SqlValidationError("System tables are not available through the kernel.")

    columns = frozenset(
        column.name.lower()
        for column in statement.find_all(exp.Column)
        if column.name
    )
    return ValidatedQuery(sql=sql.strip(), tables=tables, columns=columns)

from __future__ import annotations

from typing import List
from lark import Lark, Transformer

from .grammar import DSL_GRAMMAR
from .model import Policy, Condition, Action


def _strip_quotes(s: str) -> str:
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


class _DSLTransformer(Transformer):
    def start(self, items):
        return list(items)

    def string(self, s):
        return _strip_quotes(str(s[0]))

    def number(self, n):
        return float(n[0])

    def condition(self, items):
        field, op, value = items
        return Condition(field=str(field), op=str(op), value=value)

    def condition_list(self, items):
        return list(items)

    def restart(self, _):
        return Action(type="restart")

    def scale(self, items):
        replicas = int(float(items[0]))
        return Action(type="scale", replicas=replicas)

    def policy(self, items):
        # items[0] is ESCAPED_STRING token. Convert to str then strip quotes.
        name = _strip_quotes(str(items[0]))
        conditions = items[1]
        action = items[2]
        priority = int(float(items[3]))
        return Policy(name=name, conditions=conditions, action=action, priority=priority)


def parse_policies(text: str) -> List[Policy]:
    parser = Lark(DSL_GRAMMAR, start="start", parser="lalr")
    tree = parser.parse(text)
    result = _DSLTransformer().transform(tree)

    if isinstance(result, list):
        return [p for p in result if isinstance(p, Policy)]
    if isinstance(result, Policy):
        return [result]
    return []

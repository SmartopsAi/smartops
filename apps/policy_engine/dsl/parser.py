from typing import List

from lark import Lark, Transformer, v_args

from apps.policy_engine.dsl.model import Policy, Condition, Action


DSL_GRAMMAR = r"""
    start: policy+

    policy: "POLICY" ESCAPED_STRING ":" "WHEN" condition_list "THEN" action priority?

    priority: "PRIORITY" NUMBER

    condition_list: condition ("AND" condition)*

    condition: FIELD COMPARE value

    FIELD: "anomaly.type" | "anomaly.score" | "rca.cause" | "rca.probability"

    COMPARE: "==" | ">" | "<" | ">=" | "<="

    value: ESCAPED_STRING -> string
         | NUMBER         -> number

    action: "restart" "(" "service" ")"          -> restart
          | "scale" "(" "service" "," NUMBER ")" -> scale

    %import common.ESCAPED_STRING
    %import common.NUMBER
    %import common.WS
    %import common.NEWLINE

    %ignore WS
    %ignore NEWLINE
"""


@v_args(inline=True)
class PolicyTransformer(Transformer):
    # Top-level: always return list
    def start(self, *policies):
        return list(policies)

    # Values
    def string(self, token):
        return token.value[1:-1]

    def number(self, token):
        text = token.value
        if "." in text:
            return float(text)
        return int(text)

    # Tokens
    def FIELD(self, token):
        return token.value

    def COMPARE(self, token):
        return token.value

    # Conditions
    def condition(self, field, op, value):
        return Condition(field=field, op=op, value=value)

    def condition_list(self, first, *rest):
        conditions = [first]
        conditions.extend(rest)
        return conditions

    # Actions
    def restart(self):
        return Action(kind="restart")

    def scale(self, number):
        return Action(kind="scale", scale_replicas=int(number.value))

    # Priority (ONLY number token comes here)
    def priority(self, number_token):
        return int(number_token.value)

    # Policy (IMPORTANT FIX)
    def policy(self, name_token, conditions, action, *rest):
        """
        WHY:
        - 'rest' may contain priority or may be empty
        - This avoids Lark skipping the transformer
        """
        name = name_token.value[1:-1]

        priority = 0
        if rest:
            priority = int(rest[0])

        return Policy(
            name=name,
            conditions=conditions,
            action=action,
            priority=priority
        )


_parser = Lark(DSL_GRAMMAR, start="start", parser="lalr")


def parse_policies(text: str) -> List[Policy]:
    tree = _parser.parse(text)
    transformer = PolicyTransformer()
    return transformer.transform(tree)


def load_policies_from_file(path: str) -> List[Policy]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_policies(text)

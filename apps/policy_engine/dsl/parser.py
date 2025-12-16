from typing import List

from lark import Lark, Transformer, v_args

from apps.policy_engine.dsl.model import Policy, Condition, Action


# -------- DSL Grammar (Lark) --------
# NOTE: No '#' comments inside the grammar string.

DSL_GRAMMAR = r"""
    ?start: policy+

    policy: "POLICY" ESCAPED_STRING ":" "WHEN" condition_list "THEN" action

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
    # Top-level: list of policies
    def start(self, *policies):
        # Tree('start', [Policy, Policy, ...]) -> [Policy, Policy, ...]
        return list(policies)

    # Turn ESCAPED_STRING into a normal Python string
    def string(self, token):
        return token.value[1:-1]

    # Turn NUMBER into int or float
    def number(self, token):
        text = token.value
        if "." in text:
            return float(text)
        return int(text)

    # FIELD tokens like "anomaly.type"
    def FIELD(self, token):
        return token.value

    # COMPARE tokens: "==", ">", "<", etc.
    def COMPARE(self, token):
        return token.value

    # One Condition object
    def condition(self, field, op, value):
        return Condition(field=field, op=op, value=value)

    # List of conditions: cond AND cond AND cond...
    def condition_list(self, first, *rest):
        conditions = [first]
        conditions.extend(rest)
        return conditions

    # Actions
    def restart(self):
        return Action(kind="restart")

    def scale(self, number):
        # "scale(service, 6)" -> Action(kind="scale", scale_replicas=6)
        return Action(kind="scale", scale_replicas=int(number.value))

    # One Policy object
    def policy(self, name_token, conditions, action):
        # ESCAPED_STRING like "\"restart_on_memory_leak\"" -> restart_on_memory_leak
        name = name_token.value[1:-1]
        return Policy(name=name, conditions=conditions, action=action)



# -------- Public helper functions --------

_parser = Lark(DSL_GRAMMAR, start="start", parser="lalr")


def parse_policies(text: str) -> List[Policy]:
    """
    Parse DSL text into a list of Policy objects.
    """
    tree = _parser.parse(text)
    transformer = PolicyTransformer()
    result = transformer.transform(tree)
    return result


def load_policies_from_file(path: str) -> List[Policy]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_policies(text)

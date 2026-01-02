DSL_GRAMMAR = r"""
    start: policy+

    policy: "POLICY" ESCAPED_STRING ":" "WHEN" condition_list "THEN" action "PRIORITY" NUMBER

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

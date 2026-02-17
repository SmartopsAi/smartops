DSL_GRAMMAR = r"""
    start: policy+

    policy: "POLICY" ESCAPED_STRING ":" "WHEN" condition_list "THEN" action "PRIORITY" NUMBER

    condition_list: condition ("AND" condition)*

    condition: FIELD COMPARE value

    FIELD: /[a-zA-Z_][a-zA-Z0-9_.]*/

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

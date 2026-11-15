# Original RAT test fixture, authored for the project; contains no Python statements.
label start:
    "Hello, [player_name]! {i}Welcome{/i}."
    "Eileen" "A dialogue from a named speaker."
    "This sentence spans
        two physical lines."
    "A literal newline:\nNext line, and a quote: \"yes\"."
    menu:
        "Go left":
            "You chose the left path."
        "Go right":
            "You chose the right path."
    return

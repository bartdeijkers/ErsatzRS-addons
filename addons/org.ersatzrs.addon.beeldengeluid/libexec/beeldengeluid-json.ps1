function ConvertFrom-EscapedJsonValue([string]$Value) {
    # Next.js embeds the programme object as an escaped JSON value inside a
    # larger script string. Decode that outer string first, then parse the JSON
    # token it contains. Regex/backslash replacement loses escaped quotes.
    $jsonToken = ('"' + $Value + '"') | ConvertFrom-Json
    return $jsonToken | ConvertFrom-Json
}

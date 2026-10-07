"""Model-list capacities; defaults describe discovery, not verified upstream limits."""

DEFAULT_CONTEXT_WINDOW = 262144
DEFAULT_MAX_OUTPUT_TOKENS = 32768


def capacity_fields(row) -> dict:
    """Keep positive integer capacities only, including WorkBuddy's supplier names."""
    if not isinstance(row, dict):
        return {}
    result = {}
    for target, names in (
        ("context_window", ("context_window", "maxInputTokens", "max_input_tokens")),
        ("max_output_tokens", ("max_output_tokens", "maxOutputTokens")),
    ):
        for name in names:
            value = row.get(name)
            if type(value) is int and value > 0:
                result[target] = value
                break
    return result


def discovery_capacity(row) -> dict:
    """Publish both capacities and distinguish unspecified fields from supplied ones."""
    fields = capacity_fields(row)
    return {
        "context_window": fields.get("context_window", DEFAULT_CONTEXT_WINDOW),
        "max_output_tokens": fields.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS),
        "capacity_source": {
            key: "catalog" if key in fields else "fallback"
            for key in ("context_window", "max_output_tokens")
        },
    }


def clamp_output_tokens(payload: dict, model) -> dict:
    """Clamp explicit output budgets only when the catalog supplies a real limit."""
    limit = capacity_fields(model).get("max_output_tokens")
    if limit is None:
        return payload
    result = dict(payload)
    for key in ("max_tokens", "max_completion_tokens"):
        value = result.get(key)
        if type(value) is int and value > limit:
            result[key] = limit
    return result

"""Keep catalog reasoning metadata; never invent effort lists."""


def _effort_list(value) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        effort = item.strip()
        if not effort or effort in seen:
            continue
        seen.add(effort)
        out.append(effort)
    return out or None


def _nested_reasoning(row: dict) -> dict:
    value = row.get("reasoning")
    return value if isinstance(value, dict) else {}


def reasoning_fields(row) -> dict:
    """Keep upstream reasoning fields only. Empty lists are treated as absent."""
    if not isinstance(row, dict):
        return {}
    nested = _nested_reasoning(row)
    result: dict = {}
    for name in ("supportsReasoning", "supports_reasoning"):
        value = row.get(name)
        if isinstance(value, bool):
            result["supportsReasoning"] = value
            break
    efforts = _effort_list(nested.get("supportedEfforts") or nested.get("supported_efforts"))
    if efforts is None:
        efforts = _effort_list(row.get("supportedEfforts") or row.get("supported_efforts"))
    reasoning: dict = {}
    if efforts:
        reasoning["supportedEfforts"] = efforts
    default = None
    for source in (nested, row):
        for name in ("defaultEffort", "default_effort", "effort"):
            value = source.get(name)
            if isinstance(value, str) and value.strip():
                default = value.strip()
                break
        if default:
            break
    if default:
        reasoning["defaultEffort"] = default
    can_disable = nested.get("canDisableThinking")
    if isinstance(can_disable, bool):
        reasoning["canDisableThinking"] = can_disable
    if reasoning:
        result["reasoning"] = reasoning
    return result


def discovery_reasoning(row) -> dict:
    """Publish only catalog-supplied reasoning fields on GET /v1/models."""
    return reasoning_fields(row)

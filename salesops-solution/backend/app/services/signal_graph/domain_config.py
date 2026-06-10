_INTENT_REQUIRED_FIELDS: dict[str, dict[str, list[str]]] = {
    "keysight": {
        "po_intake": ["po_number", "ship_to", "line_items", "customer"],
        "quote_request": ["customer", "line_items"],
        "order_status": ["po_number", "customer"],
    },
}

# ordered pipeline stages (upstream -> downstream)
_STAGE_ORDER: dict[str, list[str]] = {
    "keysight": ["intake", "extract", "decide", "reply"],
}


def required_fields_for_intent(domain: str, intent: str | None) -> list[str]:
    if not intent:
        return []
    return _INTENT_REQUIRED_FIELDS.get(domain, {}).get(intent, [])


def all_intents(domain: str) -> list[str]:
    return list(_INTENT_REQUIRED_FIELDS.get(domain, {}).keys())


def stage_order(domain: str) -> list[str]:
    return _STAGE_ORDER.get(domain, [])
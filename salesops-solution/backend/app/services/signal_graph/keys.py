def target_key(metric,segment)->str:
    return f"target:{metric}@{segment}"

def metric_key(metric)->str:
    return f"metric:{metric}"

def stage_key(stage)->str:
    return f"stage:{stage}"


def raw_field_key(field)->str:
    return f"raw:pipeline:extracted.{field}"

def raw_trace_key(stage,kind)->str:
    return f"raw:trace:{stage}:{kind}"


def raw_feedback_key(stage)->str:
    return f"raw:feedback:edit:{stage}"


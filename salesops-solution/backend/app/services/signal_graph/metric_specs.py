from typing import Callable,Optional
from pydantic import BaseModel, ConfigDict


class Input(BaseModel):
    model_config= ConfigDict(frozen=True)
    key_template: str
    stream: str
    role: str
    
class MetricSpec(BaseModel):
    model_config= ConfigDict(frozen=True)
    key:str
    stage:str
    segment_dimension:str
    direction: str
    inputs: list[Input]
    compute: Callable[[list[float]],Optional[float]]
    
    
def ratio_compute(item)->Optional[float]:
    if not item:
        return None
    
    return (sum(item)/len(item))

# Nested by domain so any client can have its own catalog:
#   _REGISTRY[domain][metric_key] = MetricSpec
_REGISTRY: dict[str, dict[str, MetricSpec]] = {}

def _register(domain: str, spec: MetricSpec) -> None:
    _REGISTRY.setdefault(domain, {})[spec.key] = spec


def get_spec(domain: str, key: str) -> MetricSpec:
    return _REGISTRY[domain][key]


def has_spec(domain: str, key: str) -> bool:
    return key in _REGISTRY.get(domain, {})


def all_specs(domain: str) -> list[MetricSpec]:
    return list(_REGISTRY.get(domain, {}).values())

_register("keysight", MetricSpec(
    key="extraction_completeness",
    stage="extract",
    segment_dimension="intent",
    direction="min",
    inputs=[
        Input(key_template="raw:pipeline:extracted.{required_field}", stream="traceback", role="field_present"),
        Input(key_template="raw:trace:extract:stage_error",stream= "traceback", role="stage_health"),
        Input(key_template="raw:feedback:edit:extract", stream="feedback", role="human_correction"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="reply_send_success_rate",
    stage="reply",
    segment_dimension="global",
    direction="min",
    inputs=[
        Input(key_template="raw:trace:reply:stage_error", stream="traceback", role="stage_health"),
        Input(key_template="raw:feedback:edit:reply",stream= "feedback",role="human_correction"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="intent_classification_accuracy",
    stage="intake",
    segment_dimension="intent",
    direction="min",
    inputs=[
        Input(key_template="raw:pipeline:shadow_disagreement", stream="traceback", role="proxy_disagreement"),
        Input(key_template="raw:feedback:edit:intake", stream="feedback", role="human_correction"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="routing_accuracy",
    stage="decide",
    segment_dimension="intent",
    direction="min",
    inputs=[
        Input(key_template="raw:pipeline:routing_overridden", stream="traceback", role="proxy_override"),
        Input(key_template="raw:feedback:edit:route", stream="feedback", role="human_correction"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="customer_match_accuracy",
    stage="extract",
    segment_dimension="customer",
    direction="min",
    inputs=[
        Input(key_template="raw:pipeline:customer_match_low_conf",stream= "traceback", role="proxy_lowconf"),
        Input(key_template="raw:feedback:edit:extract", stream="feedback", role="human_correction"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="response_latency_p95",
    stage="reply",
    segment_dimension="global",
    direction="max",
    inputs=[
        Input(key_template="raw:trace:extract:duration_ms", stream="traceback", role="latency"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="automation_rate",
    stage="decide",
    segment_dimension="intent",
    direction="min",
    inputs=[
        Input(key_template="raw:pipeline:autonomy_is_l4", stream="traceback", role="field_present"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="hitl_escalation_rate",
    stage="decide",
    segment_dimension="intent",
    direction="max",
    inputs=[
         Input(key_template="raw:trace:decide:hitl_created", stream="traceback", role="stage_health"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="reopen_rate",
    stage="reply",
    segment_dimension="global",
    direction="max",
    inputs=[
        Input(key_template="raw:feedback:restore:intake", stream="feedback", role="human_correction"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="cost_per_case",
    stage="decide",
    segment_dimension="global",
    direction="max",
    inputs=[
        Input(key_template="raw:pipeline:cost_usd",stream= "traceback", role="cost"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="reply_quality_score",
    stage="reply",
    segment_dimension="intent",
    direction="min",
    inputs=[

        Input(key_template="raw:feedback:edit:reply", stream="feedback",role= "human_correction"),
        Input(key_template="raw:pipeline:reply_grade", stream="traceback", role="proxy_grade"),
    ],
    compute=ratio_compute,
))

_register("keysight", MetricSpec(
    key="intent_distribution_psi",
    stage="intake",
    segment_dimension="global",
    direction="max",
    inputs=[
        Input(key_template="raw:pipeline:intent_distribution", stream="traceback", role="distribution"),
    ],
    compute=ratio_compute,
))

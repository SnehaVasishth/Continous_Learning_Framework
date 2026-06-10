

import json

from ....agents.llm import ask_llm      
from .schema import Signal, CandidateGate


_SYSTEM = (
    "You are proposing baseline QUALITY GATES for a software system, given a list of its observable "
    "signals. A gate is a metric over one or more signals that is worth monitoring. Do NOT set any "
    "threshold/target number (a human will). For each gate give a compute type from "
    "[rate, ratio, p95, psi, count, mean], a direction ('min' = higher-is-better, 'max' = lower-is-better), "
    "and 'inputs' = the list of signal keys it is computed from. "
    "Return JSON: {\"gates\":[{\"key\",\"description\",\"direction\",\"compute\",\"inputs\",\"segment_dimension\",\"rationale\"}]}."
)


def propose_gates(signals: list[Signal]) -> list[CandidateGate]:
    """Run Pass 2 and return the validated candidate gates."""
    signal_list = [{"key": s.key, "description": s.description, "stream": s.stream} for s in signals]
    user = "SIGNALS:\n" + json.dumps(signal_list, indent=2)
    data = ask_llm(system=_SYSTEM, user=user, json_only=True)
    raw = (data or {}).get("gates", []) if isinstance(data, dict) else []

    valid_keys = {s.key for s in signals}
    out: list[CandidateGate] = []
    for item in raw:
        try:
            gate = CandidateGate(**item)
        except Exception:
            continue
        gate.inputs = [k for k in gate.inputs if k in valid_keys]   
        if gate.inputs:                                            
            out.append(gate)
    return out

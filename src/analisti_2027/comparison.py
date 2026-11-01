"""A/B/C and matched cash controls on identical supplied synthetic paths."""
from copy import deepcopy
from .simulation import simulate, number, numeric_context

ASSETS = {"AVGO", "NVDA", "AMZN", "ShinEtsu", "cash"}

def compare(mandate, timeline, entries, rules, *, data_kind):
    with numeric_context():
        return _compare(deepcopy(mandate), deepcopy(timeline), deepcopy(entries), deepcopy(rules), data_kind)

def _compare(mandate, timeline, entries, rules, data_kind):
    if data_kind != "synthetic":
        raise ValueError("Only synthetic comparisons supported")
    if mandate.get("information_cutoff") != "2026-10-27" or number(mandate.get("capital_eur")) != 3000:
        raise ValueError("Unexpected frozen mandate")
    portfolios = mandate.get("portfolios")
    if not isinstance(portfolios, dict) or set(portfolios) != {"A", "B", "C"}:
        raise ValueError("A/B/C are required")
    if not isinstance(entries, dict) or set(entries) != {"I1", "I2"}:
        raise ValueError("Explicit I1 and I2 schedules required")
    cases = {}
    for label in ("A", "B", "C"):
        p = portfolios[label]
        if not isinstance(p, dict) or set(p) != ASSETS:
            raise ValueError("Unexpected portfolio instruments")
        amounts = {a: number(v) for a, v in p.items()}
        if sum(amounts.values()) != 3000:
            raise ValueError("Invalid portfolio budget")
        for control in (False, True):
            budget = {a: v for a, v in amounts.items() if a != "cash"}
            reserve = amounts["cash"]
            if control:
                reserve += budget.pop("ShinEtsu")
            for mode in ("I1", "I2"):
                name = label + ("_no_ShinEtsu" if control else "") + "_" + mode
                cases[name] = simulate(budget, reserve, timeline, entries[mode], mode, rules, data_kind=data_kind)
    cases["cash_I3"] = simulate({}, "3000", timeline, [], "I3", {}, data_kind=data_kind)
    return {"schema_version": 1, "data_kind": "synthetic", "financially_validated": False,
            "information_cutoff": mandate["information_cutoff"], "cases": cases,
            "input_snapshot": {"mandate": mandate, "timeline": timeline, "entries": entries, "rules": rules},
            "benchmarks": "ND: total-return inputs and method not implemented",
            "limitations": ["No probabilities or recommendations", "No dividends, splits, liquidation costs or taxes", "Shared I3 is identical for A/B/C", "No actual 2027 prices or verified broker terms"]}

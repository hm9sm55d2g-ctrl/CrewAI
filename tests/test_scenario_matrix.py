"""Parametrized real offline pipeline; no LLM, network or broker calls."""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal as D
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import pytest
from analisti_2027.integration import prepare, finish, summary
from analisti_2027.quality import SECTIONS, END, audit
from analisti_2027.report_contract import bind_report, split_sections, contract_errors

ASSETS = ("AVGO", "NVDA", "AMZN", "ShinEtsu")
CASES = ("flat", "fees", "growth", "crash_recovery", "late_crash", "fx_only", "shin_shock", "whole_units")

@dataclass(frozen=True)
class RunConfig:
    fixed_fee: str
    quantity_step: str

@pytest.fixture(params=[RunConfig("0", "0.001"), RunConfig("1", "1")], ids=["fractional_free", "whole_fee"])
def run_config(request):
    return request.param

@pytest.fixture(params=CASES, ids=CASES)
def scenario_name(request):
    return request.param

@pytest.fixture
def bundle_factory():
    def make(name="flat", *, config=None, scenarios=("H1",), mutate=None):
        if name not in CASES or not scenarios or not set(scenarios) <= {"H1", "H2", "H10"}:
            raise ValueError("Invalid fixture or scenario IDs")
        cfg = config or RunConfig("0", "0.001")
        dates = ("2027-01-04", "2027-02-01", "2027-03-01", "2027-12-31")
        path = {"growth":["100","110","120","150"], "crash_recovery":["100","50","75","100"], "late_crash":["100","100","100","50"]}.get(name, ["100"] * 4)
        timeline = []
        for index, date in enumerate(dates):
            quotes = {}
            for asset in ASSETS:
                price = "10" if name == "shin_shock" and asset == "ShinEtsu" and index == 3 else path[index]
                fx = D("0.006") if asset == "ShinEtsu" else D("0.9")
                if name == "fx_only" and index == 3:
                    fx *= D("0.8")
                quotes[asset] = dict(price=price, eur_per_quote=str(fx))
            timeline.append(dict(date=date, quotes=quotes))
        spec = dict(assumptions=f"SYNTHETIC TECHNICAL FIXTURE {name}: invented prices, FX, fees and lots; not a forecast or broker terms.",
            timeline=timeline, entries={"I1":[dates[0]], "I2":list(dates[:3])},
            rules={a:dict(quantity_step="1" if name == "whole_units" else cfg.quantity_step,
                fixed_fee_eur="1" if name == "fees" else cfg.fixed_fee, commission_bps="0", fx_fee_bps="0") for a in ASSETS})
        bundle = dict(data_kind="synthetic", scenarios={sid:deepcopy(spec) for sid in scenarios})
        if mutate is not None:
            mutate(bundle)
        return bundle
    return make

@pytest.fixture
def workspace_factory(tmp_path, monkeypatch):
    with TemporaryDirectory(prefix="matrix-", dir=tmp_path) as directory:
        base = Path(directory)
        with monkeypatch.context() as mp:
            mp.chdir(base)
            mp.delenv("OPENAI_API_KEY", raising=False)
            mp.setenv("OTEL_SDK_DISABLED", "true")
            created = []
            def make():
                root = base / f"run-{len(created)}"
                (root / "knowledge").mkdir(parents=True)
                values = ((750,600,600,450,600),(900,750,750,600,0),(600,450,450,300,1200))
                portfolios = {p:dict(zip((*ASSETS,"cash"), amounts)) for p,amounts in zip("ABC",values)}
                mandate = dict(capital_eur=3000, information_cutoff="2026-10-27", portfolios=portfolios)
                (root / "knowledge/mandato.json").write_text(json.dumps(mandate), encoding="utf-8")
                (root / "knowledge/evidenze.txt").write_text("Synthetic tests only; no verified financial evidence.", encoding="utf-8")
                created.append(root)
                return root
            yield make
    assert not base.exists()

@pytest.fixture
def draft_factory():
    def make(*, section_overrides=None):
        parts = ["ND: synthetic draft; semantic review required." for _ in SECTIONS]
        for index, text in (section_overrides or {}).items():
            parts[index] = text
        raw = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + title + "\n" + body for title,body in zip(SECTIONS,parts)) + "\n\n" + END
        return SimpleNamespace(raw=raw, pydantic=None, json_dict=None,
            tasks_output=[SimpleNamespace(raw=raw, pydantic=None, json_dict=None)])
    return make

@pytest.fixture
def pipeline_factory(workspace_factory, draft_factory):
    def run(bundle, *, root=None, draft=None):
        root = workspace_factory() if root is None else root
        draft = draft_factory() if draft is None else draft
        context = prepare(root, bundle)
        bound = bind_report(draft, root, root / "binding")
        final = finish(bound, context, root, root / "integration")
        return SimpleNamespace(root=root, draft=draft, bound=bound, final=final, context=context)
    return run

def test_matrix(scenario_name, run_config, bundle_factory, pipeline_factory):
    bundle = bundle_factory(scenario_name, config=run_config)
    before = deepcopy(bundle)
    run = pipeline_factory(bundle)
    cases = run.context["numeric_results"]["H1"]["cases"]
    assert len(cases) == 13
    assert bundle == before
    assert split_sections(run.final.raw)[5] == summary(run.context)
    assert run.final.tasks_output[-1].raw == run.final.raw
    assert contract_errors(run.final.raw, run.context["mandate"]) == []
    assert audit(run.final.raw, run.context["mandate"], [], run.root)["checks_passed"]
    assert D(cases["cash_I3"]["final_value_eur"]) == 3000
    for case in cases.values():
        assert D(case["fees_eur"]) >= 0
        assert all(D(v["cash_eur"]) >= 0 for v in case["valuations"])
        if scenario_name in ("flat", "fees", "whole_units"):
            assert D(case["final_value_eur"]) == D(3000) - D(case["fees_eur"])
    if scenario_name in ("late_crash", "fx_only"):
        assert D(cases["A_I1"]["return_fraction"]) < 0
        assert D(cases["A_I1"]["max_drawdown_fraction"]) > 0
    if scenario_name == "crash_recovery":
        assert D(cases["A_I1"]["max_drawdown_fraction"]) > 0
    if scenario_name == "shin_shock":
        control = cases["A_no_ShinEtsu_I1"]
        assert D(control["final_value_eur"]) == D(3000) - D(control["fees_eur"])
        assert D(cases["A_I1"]["final_value_eur"]) < D(control["final_value_eur"])
    saved = list((run.root / "integration").glob("*.json"))
    assert len(saved) == 1
    artifact = json.loads(saved[0].read_text(encoding="utf-8"))
    assert artifact["final_report"] == run.final.raw
    assert artifact["context"]["numeric_results"] == run.context["numeric_results"]
    assert artifact["financially_validated"] is False

@pytest.mark.parametrize("scenarios", [("H1",), ("H1","H2","H10")], ids=["one","three"])
def test_dynamic_scenario_count(scenarios, bundle_factory, pipeline_factory):
    run = pipeline_factory(bundle_factory(scenarios=scenarios))
    assert sum(len(v["cases"]) for v in run.context["numeric_results"].values()) == 13 * len(scenarios)

@pytest.mark.parametrize("fault,expected", [("missing_quote","Missing or unsupported quote"), ("wrong_month","January, February, March"), ("zero_fx","Invalid numeric input")])
def test_invalid_inputs(fault, expected, bundle_factory, workspace_factory):
    def corrupt(bundle):
        spec = bundle["scenarios"]["H1"]
        if fault == "missing_quote":
            del spec["timeline"][0]["quotes"]["NVDA"]
        elif fault == "wrong_month":
            spec["entries"]["I2"][-1] = "2027-12-31"
        else:
            spec["timeline"][0]["quotes"]["NVDA"]["eur_per_quote"] = "0"
    root = workspace_factory()
    with pytest.raises(ValueError, match=expected):
        prepare(root, bundle_factory(mutate=corrupt))
    assert not (root / "integration").exists()

def test_factory_independence(bundle_factory, workspace_factory):
    first, second = bundle_factory(), bundle_factory()
    first["scenarios"]["H1"]["timeline"][0]["quotes"]["AVGO"]["price"] = "1"
    assert second["scenarios"]["H1"]["timeline"][0]["quotes"]["AVGO"]["price"] == "100"
    assert workspace_factory() != workspace_factory()

def test_no_implicit_bundle(pipeline_factory):
    run = pipeline_factory(None)
    assert run.context["status"] == "not_configured"
    assert run.context["numeric_results"] == {}
    assert run.final.raw == run.bound.raw

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from decimal import Decimal as D, localcontext, Inexact, ROUND_DOWN, ROUND_UP
from fractions import Fraction

PACKAGE = Path(__file__).resolve().parents[1] / "src/analisti_2027"
name = "_synthetic_test_package"
if name not in sys.modules:
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(PACKAGE)]
    sys.modules[name] = pkg
from _synthetic_test_package import simulation as sim, comparison as cmp, synthetic_bridge as bridge

def fixture():
    portfolios = {"A": {"AVGO":750,"NVDA":600,"AMZN":600,"ShinEtsu":450,"cash":600},
                  "B": {"AVGO":900,"NVDA":750,"AMZN":750,"ShinEtsu":600,"cash":0},
                  "C": {"AVGO":600,"NVDA":450,"AMZN":450,"ShinEtsu":300,"cash":1200}}
    mandate = {"capital_eur":3000,"information_cutoff":"2026-10-27","portfolios":portfolios}
    ds = ["2027-01-04","2027-02-01","2027-03-01","2027-12-30"]
    rows = [{"date":d,"quotes":{a:{"price":"100","eur_per_quote":"1"} for a in cmp.ASSETS if a != "cash"}} for d in ds]
    rules = {a:{"quantity_step":"0.01","fixed_fee_eur":"0","commission_bps":"0","fx_fee_bps":"0"} for a in cmp.ASSETS if a != "cash"}
    entries = {"I1":[ds[0]],"I2":ds[:3]}
    return mandate, rows, entries, rules

def single(last="100", price="100", step="1", bps="0"):
    return sim.simulate({"X":"3000"},"0",[{"date":d,"quotes":{"X":{"price":p,"eur_per_quote":"1"}}} for d,p in [("2027-01-04",price),("2027-12-30",last)]],["2027-01-04"],"I1",{"X":{"quantity_step":step,"fixed_fee_eur":"0","commission_bps":bps,"fx_fee_bps":"0"}},data_kind="synthetic")

class RegressionTests(unittest.TestCase):
    def test_tiny_step_terminates_with_bounded_iterations(self):
        r = single(price="7",step="0.000000000001",bps="1")
        self.assertLessEqual(r["orders"][0]["search_iterations"], 64)
        self.assertLessEqual(D(r["orders"][0]["spent_eur"]),D(3000))
    def test_tiny_step_quantity_is_maximal(self):
        r = single(price="7",step="0.000000000001",bps="1")
        with sim.numeric_context():
            nxt = D(r["holdings"]["X"]) + D("0.000000000001")
            gross = nxt * 7
            fee = (gross / 10000).quantize(D("0.01"),rounding=sim.ROUND_CEILING)
            self.assertGreater(gross+fee,D(3000))
    def test_caller_rounding_does_not_change_output(self):
        with localcontext() as c:
            c.rounding=ROUND_DOWN
            down=single(price="7",last="101")
        with localcontext() as c:
            c.rounding=ROUND_UP
            up=single(price="7",last="101")
        self.assertEqual(down,up)
    def test_caller_traps_do_not_change_output(self):
        expected=single(price="7")
        with localcontext() as c:
            c.traps[Inexact]=True
            self.assertEqual(single(price="7"),expected)
    def test_caller_context_restored(self):
        with localcontext() as c:
            c.prec=7
            c.rounding=ROUND_UP
            c.traps[Inexact]=True
            single(price="7")
            self.assertEqual(c.prec,7)
            self.assertEqual(c.rounding,ROUND_UP)
            self.assertTrue(c.traps[Inexact])
    def test_total_loss(self):
        r=single(last="0")
        self.assertEqual(D(r["final_value_eur"]),0)
        self.assertEqual(D(r["return_fraction"]),-1)
        self.assertEqual(D(r["max_drawdown_fraction"]),1)
    def test_zero_execution_price_remains_cash(self):
        r=single(price="0",last="100")
        self.assertEqual(D(r["final_value_eur"]),3000)
        self.assertEqual(D(r["fees_eur"]),0)
        self.assertEqual(r["orders"][0]["reason"],"zero_execution_price")
    def test_negative_price_still_rejected(self):
        with self.assertRaises(ValueError):single(last="-1")
    def test_extreme_input_rejected(self):
        for v in ("1e-13","1e13","1234567890123456789012345","abc"):
            with self.subTest(value=v):
                with self.assertRaises(ValueError):single(price=v)
    def test_search_matches_independent_fraction_oracle(self):
        for mark in ("0.3","7","100.03"):
            for fee in ("0","0.001","1"):
                for rate in ("0","0.0001","0.1"):
                    budget=Fraction(20)
                    p,f,r=map(Fraction,(mark,fee,rate))
                    def exact_cost(k):
                        if not k:return Fraction(0)
                        raw=(f+k*p*r)*100
                        ceil=-(-raw.numerator//raw.denominator)
                        return k*p+Fraction(ceil,100)
                    expected=max(k for k in range(int(budget/p)+1) if exact_cost(k)<=budget)
                    with sim.numeric_context():
                        qty,gross,cost,_=sim.affordable_quantity(D(20),D(mark),D(1),D(fee),D(rate))
                    self.assertEqual(qty,D(expected))
                    self.assertEqual(Fraction(gross+cost),exact_cost(expected))

class ComparisonTests(unittest.TestCase):
    def test_thirteen_cases(self):
        r=cmp.compare(*fixture(),data_kind="synthetic")
        self.assertEqual(len(r["cases"]),13)
        self.assertTrue(all(D(x["final_value_eur"])==3000 for x in r["cases"].values()))
        self.assertFalse(r["financially_validated"])
    def test_controls_replace_only_shinetsu(self):
        r=cmp.compare(*fixture(),data_kind="synthetic")
        for label,reserve in (("A",1050),("B",600),("C",1500)):
            base=r["cases"][label+"_I1"]
            ctrl=r["cases"][label+"_no_ShinEtsu_I1"]
            self.assertEqual(D(ctrl["reserve_eur"]),reserve)
            self.assertNotIn("ShinEtsu",ctrl["holdings"])
            for a in ("AVGO","NVDA","AMZN"):
                self.assertEqual(ctrl["holdings"][a],base["holdings"][a])
    def test_i2_keeps_future_tranches(self):
        r=cmp.compare(*fixture(),data_kind="synthetic")
        self.assertEqual(D(r["cases"]["A_I2"]["valuations"][0]["future_tranches_eur"]),1600)
    def test_no_mutation_and_snapshot_is_independent(self):
        args=fixture();before=json.dumps(args,sort_keys=True)
        r=cmp.compare(*args,data_kind="synthetic")
        self.assertEqual(json.dumps(args,sort_keys=True),before)
        args[0]["portfolios"]["A"]["AVGO"]=0
        self.assertEqual(r["input_snapshot"]["mandate"]["portfolios"]["A"]["AVGO"],750)
    def test_non_synthetic_rejected(self):
        with self.assertRaises(ValueError):cmp.compare(*fixture(),data_kind="real")
    def test_bad_mandate_rejected(self):
        args=fixture();args[0]["portfolios"]["A"]["AVGO"]=0
        with self.assertRaises(ValueError):cmp.compare(*args,data_kind="synthetic")
    def test_bad_cutoff_rejected(self):
        args=fixture();args[0]["information_cutoff"]="2026-10-28"
        with self.assertRaises(ValueError):cmp.compare(*args,data_kind="synthetic")
    def test_missing_quote_rejected(self):
        args=fixture();del args[1][0]["quotes"]["NVDA"]
        with self.assertRaises(ValueError):cmp.compare(*args,data_kind="synthetic")
    def test_costs_reconcile(self):
        args=fixture()
        for rule in args[3].values():rule["fixed_fee_eur"]="1"
        r=cmp.compare(*args,data_kind="synthetic")
        for case in r["cases"].values():
            self.assertEqual(D(case["final_value_eur"])+D(case["fees_eur"]),3000)

class BridgeTests(unittest.TestCase):
    def test_contract_build_does_not_execute(self):
        calls=[]
        class Component:
            def __init__(self,**kwargs):
                self.kwargs=kwargs
                calls.append(kwargs)
            def kickoff(self):raise AssertionError("Must not execute")
        crew,payload=bridge.build_synthetic_crew(*fixture(),data_kind="synthetic",llm="explicit-test-model",components=(Component,Component,Component,types.SimpleNamespace(sequential="sequential")))
        self.assertEqual(len(calls),3)
        self.assertEqual(len(payload["cases"]),13)
        self.assertFalse(calls[0]["allow_delegation"])
        self.assertEqual(calls[0]["tools"],[])
        self.assertIn("SCENARI SINTETICI - NON PREVISIONI",calls[1]["description"])
        self.assertFalse(crew.kwargs["memory"])
    def test_bridge_requires_explicit_llm(self):
        with self.assertRaises(ValueError):bridge.build_synthetic_crew(*fixture(),data_kind="synthetic",llm=None)
    def test_bridge_rejects_real_data_before_import(self):
        with self.assertRaises(ValueError):bridge.build_synthetic_crew(*fixture(),data_kind="real",llm="test")

if __name__ == "__main__":
    unittest.main()

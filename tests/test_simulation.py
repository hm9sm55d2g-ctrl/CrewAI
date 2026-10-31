import importlib.util
from pathlib import Path
import unittest
from decimal import Decimal as D

spec = importlib.util.spec_from_file_location("simulation", Path(__file__).resolve().parents[1] / "src/analisti_2027/simulation.py")
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

def quote(price="100", fx="1"):
    return {"X": {"price": price, "eur_per_quote": fx}}

def run(budget="3000", reserve="0", price="100", fx="1", fixed="0", step="1", mode="I1", rows=None, entries=None, commission="0", fx_fee="0"):
    if rows is None:
        rows = [{"date": d, "quotes": quote(price, fx)} for d in ["2027-01-04", "2027-12-30"]]
    rules = {"X": {"quantity_step": step, "fixed_fee_eur": fixed, "commission_bps": commission, "fx_fee_bps": fx_fee}}
    if entries is None:
        entries = [] if mode == "I3" else ["2027-01-04"]
    return sim.simulate({"X": budget}, reserve, rows, entries, mode, rules, data_kind="synthetic")

class SimulationTests(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(D(run()["final_value_eur"]), D(3000))
    def test_fee(self):
        r = run(fixed="1")
        self.assertEqual(D(r["final_value_eur"]), D(2999))
        self.assertEqual(D(r["holdings"]["X"]), D(29))
    def test_fx(self):
        rows = [{"date": "2027-01-04", "quotes": quote()}, {"date": "2027-12-30", "quotes": quote("100", "0.8")}]
        self.assertEqual(D(run(rows=rows)["final_value_eur"]), D(2400))
    def test_drawdown(self):
        rows = [{"date": d, "quotes": quote(p)} for d, p in [("2027-01-04", "100"), ("2027-06-01", "80"), ("2027-12-30", "120")]]
        r = run(rows=rows)
        self.assertEqual(D(r["max_drawdown_fraction"]), D("0.2"))
        self.assertEqual(D(r["final_value_eur"]), D(3600))
    def test_unavailable_lot(self):
        r = run(price="4000")
        self.assertEqual(D(r["residual_eur"]), D(3000))
        self.assertEqual(r["orders"][0]["status"], "not_executable")
    def test_fractional(self):
        self.assertEqual(D(run(price="2000", step="0.1")["holdings"]["X"]), D("1.5"))
    def test_i3(self):
        self.assertEqual(D(run(mode="I3")["final_value_eur"]), D(3000))
    def test_i2(self):
        dates = ["2027-01-04", "2027-02-01", "2027-03-01"]
        r = run(rows=[{"date": d, "quotes": quote()} for d in dates], entries=dates, mode="I2")
        self.assertEqual([D(x["future_tranches_eur"]) for x in r["valuations"]], [D(2000), D(1000), D(0)])
        self.assertEqual(D(r["final_value_eur"]), D(3000))
    def test_reserve(self):
        self.assertEqual(D(run(budget="2400", reserve="600")["reserve_eur"]), D(600))
    def test_bad_budget(self):
        with self.assertRaises(ValueError): run(budget="3001")
    def test_missing_quote(self):
        with self.assertRaises(ValueError): run(rows=[{"date": "2027-01-04", "quotes": {}}])
    def test_missing_rules(self):
        with self.assertRaises(ValueError): sim.simulate({"X": "3000"}, "0", [{"date": "2027-01-04", "quotes": quote()}], ["2027-01-04"], "I1", {}, data_kind="synthetic")
    def test_non_synthetic(self):
        with self.assertRaises(ValueError): sim.simulate({}, "3000", [{"date": "2027-01-04"}], [], "I3", {}, data_kind="real")
    def test_duplicate_dates(self):
        row = {"date": "2027-01-04", "quotes": quote()}
        with self.assertRaises(ValueError): run(rows=[row, row])
    def test_nan(self):
        with self.assertRaises(ValueError): run(price="NaN")
    def test_float(self):
        with self.assertRaises(ValueError): run(price=100.0)
    def test_cost_rounding(self):
        r = run(step="0.01", commission="12", fx_fee="8", fixed="1")
        self.assertLessEqual(D(r["orders"][0]["spent_eur"]), D(3000))
        self.assertEqual(D(r["final_value_eur"]) + D(r["fees_eur"]), D(3000))
    def test_single_observation(self):
        self.assertIsNone(run(rows=[{"date": "2027-01-04", "quotes": quote()}])["max_drawdown_fraction"])
    def test_i2_wrong_months(self):
        ds = ["2027-01-04", "2027-02-01", "2027-04-01"]
        with self.assertRaises(ValueError): run(mode="I2", rows=[{"date": d, "quotes": quote()} for d in ds], entries=ds)
    def test_i2_cents(self):
        ds = ["2027-01-04", "2027-02-01", "2027-03-01"]
        r = run(budget="1000", reserve="2000", mode="I2", rows=[{"date": d, "quotes": quote()} for d in ds], entries=ds)
        self.assertEqual([D(o["tranche_eur"]) for o in r["orders"]], [D("333.33"), D("333.33"), D("333.34")])
    def test_unsupported_events(self):
        with self.assertRaises(ValueError): run(rows=[{"date": "2027-01-04", "quotes": quote(), "dividend": "1"}])
    def test_i3_rejects_orders(self):
        with self.assertRaises(ValueError): run(mode="I3", entries=["2027-01-04"])
    def test_negative_fx(self):
        with self.assertRaises(ValueError): run(fx="-1")
    def test_negative_fee(self):
        with self.assertRaises(ValueError): run(fixed="-1")

if __name__ == "__main__":
    unittest.main()

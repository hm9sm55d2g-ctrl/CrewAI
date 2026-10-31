"""Offline synthetic scenarios. No orders, forecasts or financial certification."""
from datetime import date
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING, localcontext

CENT = D("0.01")

def number(value, positive=False):
    if isinstance(value, (float, bool)):
        raise ValueError("Use decimal strings or integers")
    x = D(value)
    if not x.is_finite() or x < 0 or (positive and x == 0):
        raise ValueError("Invalid numeric input")
    return x

def simulate(budgets, reserve, timeline, entry_dates, mode, rules, *, data_kind):
    """FX: EUR per quote-currency unit. Costs explicit; budget includes fees.
    Each tranche is independent: its residual is never reinvested.
    Prices must be unadjusted synthetic marks. No dividends, splits or sales.
    """
    with localcontext() as ctx:
        ctx.prec = 40
        return _simulate(budgets, reserve, timeline, entry_dates, mode, rules, data_kind)

def _simulate(budgets, reserve, timeline, entry_dates, mode, rules, data_kind):
    if data_kind != "synthetic" or mode not in ("I1", "I2", "I3"):
        raise ValueError("Only synthetic I1/I2/I3 scenarios supported")
    b = {a: number(v) for a, v in budgets.items()}
    reserve = number(reserve)
    if any(x != x.quantize(CENT) for x in [reserve, *b.values()]):
        raise ValueError("Budgets must be in cents")
    if reserve + sum(b.values()) != D(3000):
        raise ValueError("Capital must equal EUR 3000")
    if not timeline or any(set(row) - {"date", "quotes"} for row in timeline):
        raise ValueError("Empty timeline or unsupported events")
    dates = [row["date"] for row in timeline]
    if dates != sorted(set(dates)) or any(date.fromisoformat(d).isoformat() != d or date.fromisoformat(d).year != 2027 for d in dates):
        raise ValueError("Unique ordered ISO dates in 2027 required")
    if mode == "I3":
        if entry_dates:
            raise ValueError("I3 has no entry dates")
        return {"data_kind": "synthetic", "financially_validated": False,
                "final_value_eur": "3000", "return_fraction": "0", "max_drawdown_fraction": "0",
                "reserve_eur": "3000", "future_tranches_eur": "0", "residual_eur": "0",
                "fees_eur": "0", "holdings": {}, "orders": [],
                "valuations": [{"date": d, "value_eur": "3000", "cash_eur": "3000"} for d in dates],
                "liquidation_value_eur": None, "taxes": "excluded", "dividends": "unsupported"}
    count = 1 if mode == "I1" else 3
    if len(entry_dates) != count or entry_dates != sorted(set(entry_dates)) or not set(entry_dates) <= set(dates) or entry_dates[0] != dates[0]:
        raise ValueError("Invalid explicit execution dates")
    if mode == "I2" and [date.fromisoformat(d).month for d in entry_dates] != [1, 2, 3]:
        raise ValueError("I2 requires January, February, March")
    fields = {"quantity_step", "fixed_fee_eur", "commission_bps", "fx_fee_bps"}
    parsed, tranches = {}, {}
    for a, budget in b.items():
        one = (budget / count).quantize(CENT, rounding=ROUND_FLOOR)
        tranches[a] = [one] * (count - 1) + [budget - one * (count - 1)]
        if budget:
            if a not in rules or set(rules[a]) != fields:
                raise ValueError("Missing execution rules: " + a)
            parsed[a] = {k: number(rules[a][k], k == "quantity_step") for k in fields}
    holdings = {a: D(0) for a in b}
    future, residual, fees_total = sum(b.values()), D(0), D(0)
    orders, valuations = [], []
    peak, max_dd = D(3000), D(0)
    for row in timeline:
        marks = {}
        for a, budget in b.items():
            if not budget:
                continue
            q = row.get("quotes", {}).get(a)
            if not isinstance(q, dict) or set(q) != {"price", "eur_per_quote"}:
                raise ValueError("Missing or unsupported quote: " + a)
            marks[a] = number(q["price"], True) * number(q["eur_per_quote"], True)
        if row["date"] in entry_dates:
            i = entry_dates.index(row["date"])
            for a, budget in b.items():
                tranche = tranches[a][i]
                future -= tranche
                if not budget:
                    continue
                r = parsed[a]
                step = r["quantity_step"]
                rate = (r["commission_bps"] + r["fx_fee_bps"]) / D(10000)
                fixed = r["fixed_fee_eur"].quantize(CENT, rounding=ROUND_CEILING)
                quantity = (max(D(0), tranche - fixed) / (marks[a] * (1 + rate)) / step).to_integral_value(rounding=ROUND_FLOOR) * step
                def cost(qty):
                    gross = qty * marks[a]
                    fee = (r["fixed_fee_eur"] + gross * rate).quantize(CENT, rounding=ROUND_CEILING) if qty else D(0)
                    return gross, fee
                gross, fee = cost(quantity)
                while quantity > 0 and gross + fee > tranche:
                    quantity -= step
                    gross, fee = cost(quantity)
                spent = gross + fee
                holdings[a] += quantity
                residual += tranche - spent
                fees_total += fee
                orders.append({"date": row["date"], "asset": a,
                               "status": "simulated_buy" if quantity else "not_executable",
                               "tranche_eur": str(tranche), "quantity": str(quantity),
                               "gross_eur": str(gross), "fee_eur": str(fee), "spent_eur": str(spent)})
        cash = reserve + future + residual
        spent_so_far = sum(D(o["spent_eur"]) for o in orders)
        if cash < 0 or abs(cash + spent_so_far - D(3000)) > D("1e-30"):
            raise ArithmeticError("Cash reconciliation failed")
        value = cash + sum(holdings[a] * marks[a] for a in marks)
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak)
        valuations.append({"date": row["date"], "value_eur": str(value), "cash_eur": str(cash),
                           "future_tranches_eur": str(future), "residual_eur": str(residual)})
    final = D(valuations[-1]["value_eur"])
    return {"data_kind": "synthetic", "financially_validated": False,
            "final_value_eur": str(final), "return_fraction": str(final / D(3000) - 1),
            "max_drawdown_fraction": str(max_dd) if len(timeline) > 1 else None,
            "drawdown_scope": "supplied observations plus pre-entry capital; not intraday",
            "reserve_eur": str(reserve), "future_tranches_eur": str(future),
            "residual_eur": str(residual), "fees_eur": str(fees_total),
            "holdings": {a: str(q) for a, q in holdings.items()}, "orders": orders, "valuations": valuations,
            "liquidation_value_eur": None, "taxes": "excluded", "dividends": "unsupported"}

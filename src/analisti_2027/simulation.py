"""Deterministic synthetic scenarios only; no broker, forecasts or certification."""
from datetime import date
from decimal import Decimal as D, Context, DecimalException, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, InvalidOperation, DivisionByZero, Overflow, localcontext
from fractions import Fraction

CENT = D("0.01")

def numeric_context():
    return localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow]))

def number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, D)):
        raise ValueError("Use decimal strings or integers")
    try:
        x = D(value)
        if not x.is_finite() or x < 0 or (positive and not x):
            raise ValueError("Invalid numeric input")
        if len(x.as_tuple().digits) > 24 or abs(x.as_tuple().exponent) > 12:
            raise ValueError("Numeric input exceeds 24 digits / exponent +/-12")
        return x
    except DecimalException as exc:
        raise ValueError("Invalid decimal input") from exc

def affordable_quantity(tranche, mark, step, fixed, rate):
    """Binary search on integer lots; fee rounding included in feasibility."""
    def cost(units):
        gross = D(units) * step * mark
        fee = (fixed + gross * rate).quantize(CENT, rounding=ROUND_CEILING) if units else D(0)
        return gross, fee
    if not mark or not tranche:
        return D(0), D(0), D(0), 0
    lo, hi = 0, int(Fraction(tranche) / Fraction(mark) / Fraction(step))
    iterations = 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        gross, fee = cost(mid)
        if gross + fee <= tranche:
            lo = mid
        else:
            hi = mid - 1
        iterations += 1
    gross, fee = cost(lo)
    return D(lo) * step, gross, fee, iterations

def simulate(budgets, reserve, timeline, entry_dates, mode, rules, *, data_kind):
    """FX is EUR per quote unit; explicit dates, independent cost-inclusive tranches.
    Zero prices are permitted for valuation; zero-price buys remain cash.
    No sales, dividends, splits, interest, taxes or adjusted prices supported.
    """
    with numeric_context():
        return _simulate(budgets, reserve, timeline, entry_dates, mode, rules, data_kind)

def _simulate(budgets, reserve, timeline, entry_dates, mode, rules, data_kind):
    if data_kind != "synthetic" or mode not in ("I1", "I2", "I3"):
        raise ValueError("Only synthetic I1/I2/I3 scenarios supported")
    if not isinstance(budgets, dict) or not isinstance(rules, dict):
        raise ValueError("budgets and rules must be dictionaries")
    if any(not isinstance(a, str) or not a for a in budgets):
        raise ValueError("Invalid asset identifiers")
    b = {a: number(v) for a, v in budgets.items()}
    reserve = number(reserve)
    if any(x != x.quantize(CENT) for x in [reserve, *b.values()]):
        raise ValueError("Budgets must be in cents")
    if reserve + sum(b.values()) != D(3000):
        raise ValueError("Capital must equal EUR 3000")
    if not isinstance(timeline, list) or not timeline or any(not isinstance(row, dict) or set(row) - {"date", "quotes"} for row in timeline):
        raise ValueError("Empty timeline or unsupported events")
    dates = [row.get("date") for row in timeline]
    if any(not isinstance(d, str) for d in dates):
        raise ValueError("ISO date strings required")
    if dates != sorted(set(dates)) or any(date.fromisoformat(d).isoformat() != d or date.fromisoformat(d).year != 2027 for d in dates):
        raise ValueError("Unique ordered ISO dates in 2027 required")
    if not isinstance(entry_dates, list) or any(not isinstance(d, str) for d in entry_dates):
        raise ValueError("Explicit date list required")
    if mode == "I3":
        if entry_dates:
            raise ValueError("I3 has no entry dates")
        b, reserve = {}, D(3000)
    else:
        count = 1 if mode == "I1" else 3
        if len(entry_dates) != count or entry_dates != sorted(set(entry_dates)) or not set(entry_dates) <= set(dates) or entry_dates[0] != dates[0]:
            raise ValueError("Invalid explicit execution dates")
        if mode == "I2" and [date.fromisoformat(d).month for d in entry_dates] != [1, 2, 3]:
            raise ValueError("I2 requires January, February, March")
    count = 3 if mode == "I2" else 1
    fields = {"quantity_step", "fixed_fee_eur", "commission_bps", "fx_fee_bps"}
    parsed, tranches = {}, {}
    for a, budget in b.items():
        one = (budget / count).quantize(CENT, rounding=ROUND_FLOOR)
        tranches[a] = [one] * (count - 1) + [budget - one * (count - 1)]
        if budget:
            if a not in rules or not isinstance(rules[a], dict) or set(rules[a]) != fields:
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
            quotes = row.get("quotes")
            q = quotes.get(a) if isinstance(quotes, dict) else None
            if not isinstance(q, dict) or set(q) != {"price", "eur_per_quote"}:
                raise ValueError("Missing or unsupported quote: " + a)
            marks[a] = number(q["price"]) * number(q["eur_per_quote"], True)
        if row["date"] in entry_dates:
            i = entry_dates.index(row["date"])
            for a, budget in b.items():
                tranche = tranches[a][i]
                future -= tranche
                if not budget:
                    continue
                r = parsed[a]
                rate = (r["commission_bps"] + r["fx_fee_bps"]) / D(10000)
                quantity, gross, fee, iterations = affordable_quantity(tranche, marks[a], r["quantity_step"], r["fixed_fee_eur"], rate)
                spent = gross + fee
                holdings[a] += quantity
                residual += tranche - spent
                fees_total += fee
                orders.append({"date": row["date"], "asset": a,
                               "status": "simulated_buy" if quantity else "not_executable",
                               "reason": "zero_execution_price" if not marks[a] else (None if quantity else "budget_or_lot"),
                               "search_iterations": iterations, "tranche_eur": str(tranche), "quantity": str(quantity),
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
            "max_drawdown_fraction": str(max_dd) if len(timeline) > 1 or mode == "I3" else None,
            "drawdown_scope": "supplied observations plus pre-entry capital; not intraday",
            "reserve_eur": str(reserve), "future_tranches_eur": str(future),
            "residual_eur": str(residual), "fees_eur": str(fees_total),
            "holdings": {a: str(q) for a, q in holdings.items()}, "orders": orders, "valuations": valuations,
            "liquidation_value_eur": None, "taxes": "excluded", "dividends": "unsupported"}

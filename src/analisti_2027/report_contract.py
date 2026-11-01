"""Deterministic mandate blocks; original LLM draft retained, never certified."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4
from analisti_2027.quality import SECTIONS, END, audit

ASSETS = ("AVGO", "NVDA", "AMZN", "ShinEtsu", "cash")

def validated_amounts(mandate):
    date.fromisoformat(mandate["information_cutoff"])
    if mandate.get("capital_eur") != 3000 or set(mandate["portfolios"]) != {"A", "B", "C"}:
        raise ValueError("INVALID_REPORT_MANDATE")
    result = {}
    for label in ("A", "B", "C"):
        p = mandate["portfolios"][label]
        if set(p) != set(ASSETS):
            raise ValueError("INVALID_REPORT_ASSETS")
        values = []
        for asset in ASSETS:
            value = p[asset]
            if isinstance(value, (bool, float)):
                raise ValueError("Use integer or decimal-string mandate amounts")
            try:
                n = Decimal(str(value))
                if not n.is_finite() or n < 0 or n > 3000 or n != n.quantize(Decimal("0.01")):
                    raise ValueError("Invalid mandate amount")
            except InvalidOperation as exc:
                raise ValueError("Invalid mandate amount") from exc
            values.append(n)
        if sum(values) != 3000:
            raise ValueError("INVALID_REPORT_BUDGET")
        result[label] = values
    return result

def render_blocks(mandate):
    amounts = validated_amounts(mandate)
    cutoff = mandate["information_cutoff"]
    constraints = (f"Capitale complessivo: 3000 EUR per portafoglio, inclusi liquidita e costi; non un budget azionario aggiuntivo. Cutoff: {cutoff}. "
        "Nessun versamento, leva, derivato o vendita allo scoperto. Nessun ordine al broker. Baseline senza ribilanciamento; imposte escluse. "
        "Prezzi iniziali e quantita 2027 intenzionalmente sconosciuti nella versione congelata: non colmarli con dati successivi al cutoff. "
        "USD/EUR, JPY/EUR, costi e frazionabilita: ND finche non documentati. Situazione fiscale e patrimoniale: ND.")
    rows = ["Dati del mandato, non risultati o previsioni. A/B/C sono portafogli, non aziende. Importi in EUR.",
            "|Portafoglio|AVGO|NVDA|AMZN|Shin-Etsu|Cassa|Totale|", "|---|---:|---:|---:|---:|---:|---:|"]
    fmt = lambda x: format(x, "f")
    for label, values in amounts.items():
        rows.append("|" + "|".join([label, *map(fmt, values), "3000"]) + "|")
    rows += ["", "Controlli: sostituire soltanto Shin-Etsu con cassa; altri budget invariati."]
    for label, values in amounts.items():
        rows.append(f"- {label} senza Shin-Etsu: Shin-Etsu 0 EUR; cassa {fmt(values[3] + values[4])} EUR.")
    rows += ["I1: ingresso iniziale secondo i budget, inclusi i costi. I2: un terzo di ciascun budget azionario a gennaio/febbraio/marzo; riserva, tranche future e residui separati.",
             "I3: 3000 EUR interamente liquidi; rendimento ipotetico 0%. Non una promessa sul rendimento della cassa.",
             "Benefici comparativi, rendimenti e drawdown: ND senza input e calcoli documentati. Nessuna strategia vincente dichiarata."]
    return constraints, "\n".join(rows)

def split_sections(text):
    body = text.strip().rsplit("\n", 1)[0]
    heads = list(re.finditer(r"^##[ \t]+(.+)$", body, re.M))
    if len(heads) != 9:
        raise ValueError("REPORT_SECTION_COUNT_INVALID")
    return [body[h.end():heads[i+1].start() if i+1 < len(heads) else len(body)].strip() for i,h in enumerate(heads)]

def contract_errors(text, mandate):
    sections = split_sections(text)
    constraints, portfolios = render_blocks(mandate)
    errors = []
    if sections[2] != constraints or sections[6] != portfolios:
        errors.append("MANDATE_BLOCK_MISMATCH")
    if re.search(r"\bH(?:1|2|10)\b", sections[3]):
        errors.append("SCENARIO_IDS_USED_AS_COMPANY_THESES")
    if re.search(r"(?im)^\s*(?:#{1,6}\s*)?[ABC]\s*(?:\(\s*(?:AVGO|NVDA|AMZN)\s*\)|[=:]\s*(?:AVGO|NVDA|AMZN)\b)", text):
        errors.append("PORTFOLIO_COMPANY_CONFUSION")
    return errors

def bind_report(result, resource_root, artifact_dir=None):
    """Return a copy with deterministic sections. Disk audit preserves draft and final.
    Sections 3/7/9 always owned by code; 1/2/4/5 use conservative templates only
    when no evidence records exist. Sections 6/8 remain LLM text requiring review.
    No claim that arbitrary financial prose has been semantically validated.
    """
    if getattr(result, "pydantic", None) is not None or getattr(result, "json_dict", None) is not None:
        raise ValueError("STRUCTURED_CREW_OUTPUT_NOT_SUPPORTED_BY_BINDER")
    root = Path(resource_root)
    mandate = json.loads((root / "knowledge/mandato.json").read_text(encoding="utf-8"))
    register = root / "knowledge/evidence_registry.json"
    records = json.loads(register.read_text(encoding="utf-8")) if register.exists() else []
    draft = result.raw
    original_audit = audit(draft, mandate, records, root)
    if not original_audit["checks_passed"]:
        raise ValueError("DRAFT_STRUCTURE_FAILED: " + "; ".join(original_audit["errors"]))
    parts = split_sections(draft)
    changed = {3, 7, 9}
    parts[2], parts[6] = render_blocks(mandate)
    cutoff = mandate["information_cutoff"]
    parts[8] = (f"Acquisire documenti e serie con data di pubblicazione entro {cutoff}, identificando fonte, periodo, unita e valuta. "
        "Non scegliere anni base senza motivazione e fonti. Prezzi iniziali 2027 restano sconosciuti nella versione congelata. "
        "Documentare costi e disponibilita dello strumento. Revisione semantica necessaria prima di ogni utilizzo decisionale.")
    if not records:
        changed.update((1, 2, 4, 5))
        parts[0] = "Nessuna evidenza finanziaria verificata acquisita. Report preliminare, non una valutazione di investimento. I blocchi del mandato e le schede prive di evidenze sono assemblati dal codice; la bozza degli agenti e conservata separatamente."
        evidence = (root / "knowledge/evidenze.txt").read_text(encoding="utf-8")
        urls = sorted(set(re.findall(r"https://[^\s<>\"']+", evidence)))
        parts[1] = "Evidenze acquisite: nessuna. Riferimenti presenti nei materiali, NON documenti letti o verificati:\n" + ("\n".join("- " + u for u in urls) if urls else "ND: nessun indirizzo fornito.")
        parts[3] = "\n\n".join("### " + a + "\nDriver, cassa, valutazione: ND, nessuna evidenza acquisita. Tesi e controtesi: ND, non formulate come fatti. Domanda: quali documenti disponibili entro il cutoff supportano queste dimensioni? Invalidazione: ND finche non e definita una tesi documentata." for a in ("AVGO", "NVDA", "AMZN"))
        parts[4] = "Attivita industriali e diversificazione industriale/geografica/finanziaria: ND, nessuna evidenza acquisita. Confronto fra detenere Shin-Etsu e trasferire il suo budget in cassa: ND senza dati quantitativi; non coincide con la liquidita aziendale. Richiesti documenti entro il cutoff."
    final = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + s + "\n" + p for s,p in zip(SECTIONS, parts)) + "\n\n" + END
    final_audit = audit(final, mandate, records, root)
    errors = final_audit["errors"] + contract_errors(final, mandate)
    if errors:
        raise ValueError("BOUND_REPORT_FAILED: " + "; ".join(errors))
    returned = deepcopy(result)
    returned.raw = final
    outputs = getattr(returned, "tasks_output", None)
    if outputs:
        if getattr(outputs[-1], "pydantic", None) is not None or getattr(outputs[-1], "json_dict", None) is not None:
            raise ValueError("STRUCTURED_TASK_OUTPUT_NOT_SUPPORTED_BY_BINDER")
        outputs[-1].raw = final
    directory = Path(artifact_dir) if artifact_dir is not None else Path("output/report_audits")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid4().hex + ".json")
    record = {"draft_raw": draft, "final_raw": final, "draft_audit": original_audit, "final_audit": final_audit,
              "replaced_sections": sorted(changed), "mandate_sha256": hashlib.sha256(json.dumps(mandate, sort_keys=True).encode()).hexdigest(),
              "financially_validated": False, "semantic_review_required": True}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT_BINDING_AUDIT " + json.dumps({"artifact": str(path), "replaced_sections": sorted(changed), "financially_validated": False}))
    return returned

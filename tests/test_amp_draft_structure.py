"""Regression for the AMP draft supplied on 2026-11-05; no LLM or AMP dispatch."""
from contextlib import redirect_stdout
from io import StringIO
import json
import re
import unittest

import test_final_output_contract as support
from analisti_2027 import quality, report_contract as contract

AMP_DRAFT = """### ANALISI PRELIMINARE NON VALIDATA

#### 1. Sintesi e stato della validazione
La raccolta di dati è iniziata il 27 ottobre 2026 e si è conclusa il 5 novembre 2026. Non sono state verificate evidenze finanziarie, rendendo impossibile una validazione completa delle informazioni analizzate. La mancanza di dati concreti limita la capacità di fornire un'analisi affidabile.

#### 2. Evidenze acquisite e riferimenti da consultare
Non sono state acquisite evidenze finanziarie verificate. Non ci sono documenti pubblicati o osservazioni di mercato nella finestra temporale che possano essere utilizzati come evidenza. Si segnala la necessità di acquisire dati e fonti per procedere con una valutazione più completa.

#### 3. Vincoli e lacune
I vincoli principali includono il budget totale di 3000 EUR, l'assenza di versamenti, leva o vendite allo scoperto, e la mancanza di dati sui prezzi e cambi. Le lacune evidenti riguardano l'assenza di informazioni sui flussi di cassa, valutazioni e costi intermediari per le aziende analizzate.

#### 4. Schede AVGO, NVDA e AMZN
**AVGO (Broadcom Inc.)**
- Driver: Innovazione nei semiconduttori.
- Cassa: ND.
- Valutazione: ND.
- Tesi: Potenziale crescita nella domanda di semiconduttori.
- Controtesi: Concorrenza crescente.

**NVDA (NVIDIA Corporation)**
- Driver: Dominanza nel mercato delle GPU.
- Cassa: ND.
- Valutazione: ND.
- Tesi: Crescita grazie all'IA e al gaming.
- Controtesi: Saturazione del mercato.

**AMZN (Amazon.com, Inc.)**
- Driver: Crescita dell'e-commerce e dei servizi cloud.
- Cassa: ND.
- Valutazione: ND.
- Tesi: Espansione della quota di mercato.
- Controtesi: Pressioni normative.

#### 5. Scheda Shin-Etsu
Non sono disponibili evidenze finanziarie verificate per Shin-Etsu. La mancanza di dati sulla diversificazione industriale e geografica impedisce una valutazione completa. È necessario acquisire informazioni specifiche per procedere.

#### 6. Scenari H1, H2 e H10
**H1**: Crescita sostenuta degli utili e della cassa nel settore tecnologico, con stabilità dei costi. 
**H2**: Compressione dei multipli di valutazione nonostante la crescita degli utili. 
**H10**: Impatto negativo simultaneo su utili e multipli a causa di eventi esterni. Questi scenari sono ipotesi sintetiche e non previsioni reali.

#### 7. Confronto A/B/C, controlli e I1/I2/I3
**A/B/C**: Tutti i confronti includono Shin-Etsu senza redistribuzione di liquidità. 
**Controlli**: Effettuati senza Shin-Etsu, mantenendo la liquidità separata. 
**I1/I2/I3**: Ingressi iniziali e successivi non sono valutabili senza dati concreti.

#### 8. Obiezioni e criticità della revisione
Le principali criticità includono la mancanza di evidenze finanziarie verificate, l'assenza di dati sui prezzi e cambi, e la confusione tra dati sintetici e reali. Questi fattori rendono difficile una valutazione accurata e richiedono ulteriori dati e fonti.

#### 9. Prossime verifiche
È necessario acquisire dati finanziari specifici per AVGO, NVDA, AMZN e Shin-Etsu, oltre a informazioni sui tassi di cambio e sulle valutazioni. Solo con queste evidenze sarà possibile procedere con una valutazione più completa.

FINE REPORT PRELIMINARE"""


class AmpDraftStructureTests(unittest.TestCase):
    setUp = support.FinalOutputContractTests.setUp
    run_hook = support.FinalOutputContractTests.run_hook

    def set_draft(self, raw):
        self.draft.raw = raw
        self.draft.tasks_output[-1].raw = raw

    def test_exact_amp_draft_reproduces_both_structure_errors(self):
        outcome = quality.audit(AMP_DRAFT, self.mandate, [], self.root, as_of=self.context["as_of"])
        self.assertEqual(set(outcome["errors"]), {"INVALID_REPORT_TITLE", "SECTION_SET_OR_ORDER_INVALID"})

    def test_rejected_draft_and_audit_saved_before_exception(self):
        self.set_draft(AMP_DRAFT)
        capture = StringIO()
        with redirect_stdout(capture):
            with self.assertRaisesRegex(ValueError, "DRAFT_STRUCTURE_FAILED") as caught:
                self.run_hook()
        for error in ("INVALID_REPORT_TITLE", "SECTION_SET_OR_ORDER_INVALID"):
            self.assertIn(error, str(caught.exception))
        paths = list((self.root / "binding").glob("*.json"))
        self.assertEqual(len(paths), 1)
        saved = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual(saved["draft_raw"], AMP_DRAFT)
        self.assertEqual(saved["status"], "draft_rejected")
        self.assertFalse(saved["draft_audit"]["checks_passed"])
        self.assertIsNone(saved["final_raw"])
        self.assertIsNone(saved["final_audit"])
        self.assertEqual(saved["expected_sections"], list(quality.SECTIONS))
        self.assertEqual(saved["observed_headings"][0], "### ANALISI PRELIMINARE NON VALIDATA")
        self.assertFalse(saved["financially_validated"])
        self.assertEqual(self.draft.raw, AMP_DRAFT)
        self.assertEqual(self.draft.tasks_output[-1].raw, AMP_DRAFT)
        self.assertFalse((self.root / "integration").exists())
        line = next(line for line in capture.getvalue().splitlines() if line.startswith("REPORT_BINDING_AUDIT "))
        self.assertEqual(json.loads(line.split(" ", 1)[1])["status"], "draft_rejected")

    def test_heading_corrected_variant_passes_and_binds(self):
        corrected = re.sub(r"^#### ", "## ", AMP_DRAFT, flags=re.M)
        corrected = corrected.replace("### ANALISI PRELIMINARE NON VALIDATA", "# ANALISI PRELIMINARE NON VALIDATA", 1)
        initial = quality.audit(corrected, self.mandate, [], self.root, as_of=self.context["as_of"])
        self.assertTrue(initial["checks_passed"], initial["errors"])
        self.set_draft(corrected)
        final = self.run_hook()
        outcome = quality.audit(final.raw, self.mandate, [], self.root, as_of=self.context["as_of"])
        self.assertTrue(outcome["checks_passed"], outcome["errors"])
        self.assertFalse(outcome["financially_validated"])
        self.assertEqual(contract.contract_errors(final.raw, self.mandate, as_of=self.context["as_of"]), [])
        for row in ("|A|750|600|600|450|600|3000|", "|B|900|750|750|600|0|3000|", "|C|600|450|450|300|1200|3000|"):
            self.assertIn(row, final.raw)
        self.assertNotIn("Dominanza nel mercato delle GPU", final.raw)
        self.assertNotIn("Espansione della quota di mercato", final.raw)
        self.assertIn("Tesi e controtesi: ND", final.raw)
        self.assertEqual(final.tasks_output[-1].raw, final.raw)
        self.assertEqual(self.draft.raw, corrected)
        self.assertEqual(final.raw.splitlines()[-1], quality.END)
        saved = json.loads(next((self.root / "binding").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(saved["draft_raw"], corrected)
        self.assertEqual(saved["final_raw"], final.raw)

    def test_report_task_contains_literal_heading_skeleton(self):
        import yaml
        config = yaml.safe_load((support.ROOT / "config/tasks.yaml").read_text(encoding="utf-8"))
        description = config["report"]["description"]
        self.assertIn("# ANALISI PRELIMINARE NON VALIDATA", description.splitlines())
        headings = re.findall(r"^## (.+)$", description, re.M)
        self.assertEqual(headings, list(quality.SECTIONS))


if __name__ == "__main__":
    unittest.main()

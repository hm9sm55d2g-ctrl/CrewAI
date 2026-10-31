# Motore numerico v0.1: scenari sintetici offline

Questo incremento non e una certificazione di correttezza finanziaria.
Non e collegato agli agenti CrewAI, a un broker o a un servizio di quotazioni.
Non modifica il mandato congelato o le istruzioni del report preliminare.

## Esecuzione dei test

Dalla radice del repository:

```sh
python -m unittest discover -s tests -p 'test_simulation.py' -v
```

Il test importa il modulo direttamente, senza CrewAI o dipendenze applicative.
La suite completa e eseguibile con il workflow quality esistente; questo commit
non modifica i trigger del workflow e non avvia un deployment.

## Contratto degli input

- `data_kind` deve essere `synthetic`: nessun risultato reale o previsione.
- `budgets`: dizionario strumento/importo EUR; `reserve`: liquidita EUR.
- Capitale totale obbligatorio: 3000 EUR. Budget e riserva al centesimo.
- Numeri come stringhe decimali o interi: float e bool rifiutati.
- `timeline`: osservazioni ordinate con date ISO uniche del 2027 e `quotes`.
- Ogni quotazione contiene `price` positivo e `eur_per_quote` positivo:
  EUR per una unita di valuta quotata. Per un prezzo in EUR, usare 1.
- Date di esecuzione esplicite presenti nelle osservazioni. Nessuna inferenza
  su giorni di borsa, disponibilita o prezzo eseguibile.
- I1: ingresso alla prima osservazione. I2: gennaio/febbraio/marzo, un terzo
  del budget di ciascuno strumento; differenze di centesimi nell'ultima tranche.
  I3: tutto liquido a rendimento ipotetico zero, senza date di acquisto.
- Per ogni strumento con budget positivo servono `quantity_step`,
  `fixed_fee_eur`, `commission_bps`, `fx_fee_bps`, anche quando pari a zero.
  Un basis point e 1/10000. Queste sono ipotesi, non condizioni del broker.

## Metodo

Decimal con precisione 40. Commissione = importo fisso per acquisto eseguito
piu basis point sul controvalore EUR; costo cambio in basis point sullo stesso
controvalore. Commissione totale arrotondata verso l'alto al centesimo.
Quantita arrotondata verso il basso al passo configurato. Il costo complessivo
non puo superare la tranche. Nessuna commissione su acquisti non eseguibili.
I budget includono i costi: non sono importi netti da investire.

Riserva, tranche future e residui restano separati. I residui non vengono
riutilizzati negli acquisti successivi. Nessuna vendita o ribilanciamento.
La riconciliazione verifica a ogni osservazione: cassa piu acquisti/costi
cumulati uguale capitale iniziale, con tolleranza numerica assoluta 1e-30 EUR.
Il valore di mercato non entra in questa identita di conservazione della cassa.
Rendimento = valore finale / 3000 - 1, espresso come frazione, non percentuale.
Drawdown: massima perdita relativa da un massimo precedente, includendo il
capitale prima degli acquisti; solo sulle osservazioni disponibili, non intraday.
Con una sola osservazione investita il drawdown resta ND (`null`).

## Output e limiti

Registro acquisti simulati, quantita, costi, residui, cassa e serie di valori EUR.
`financially_validated` resta false; i test verificano casi sintetici, non verita
finanziaria. `liquidation_value_eur` resta null: non vengono simulati costi di vendita.
Imposte escluse. Nessun interesse maturato sulla liquidita.
Dividendi, split, prezzi rettificati, benchmark total return e dati reali non
supportati. Non utilizzare questo prototipo con prezzi rettificati come prezzi
di esecuzione. Eventi aggiuntivi nelle osservazioni sono rifiutati.
Nessuna verifica documentale di fonti o calendario mercati; nessuna probabilita.

A/B/C possono essere passati separatamente come budget: manca ancora un
orchestratore che legga il mandato, generi i controlli senza Shin-Etsu e produca
una matrice comparativa. Mancano anche il collegamento CrewAI e un CLI.
Sono incrementi successivi, non funzionalita gia disponibili.

## Provenienza delle verifiche

24 test del nuovo modulo eseguiti localmente nell'ambiente di sviluppo.
Nessuna affermazione di esecuzione della suite completa o della CI remota.
Necessaria revisione indipendente prima di impieghi diversi da prove sintetiche.

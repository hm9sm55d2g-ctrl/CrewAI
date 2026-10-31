# Motore sintetico v0.2 - aggiornamento locale da revisionare

Base GitHub: aa66181095e2df6c3c22068b2e8c2120689a6ac0.
Questo pacchetto e un overlay di sei file, non un clone completo o un commit.
Nessuna certificazione finanziaria, previsione, quotazione reale o ordine.
Non modifica crew.py, config, mandato congelato, quality gate o workflow.

## Correzioni

Ricerca binaria sui lotti interi anziche riduzione lineare. La fattibilita include
la commissione totale arrotondata verso l'alto al centesimo; il test controlla
anche che un lotto aggiuntivo superi il budget. Limiti: 24 cifre significative ed
esponente decimale fra -12 e 12 sugli input. Passo minimo 1e-12.
Contesto Decimal esplicito indipendente dal chiamante: precisione 80,
ROUND_HALF_EVEN e gestione delle eccezioni aritmetiche dichiarata nel codice.
Zero ammesso nelle valorizzazioni; gli acquisti a zero non vengono eseguiti e
non generano commissioni. I prezzi negativi restano rifiutati.

## Contratto numerico

Capitale totale 3000 EUR, budget e riserva al centesimo; numeri stringa/interi
(o Decimal), niente float o bool. Cambi EUR per unita di valuta quotata.
Date ISO ordinate uniche del 2027; giorni eseguibili specificati dal chiamante,
non ricavati da un calendario mercati. Prezzi sintetici non rettificati.
Regole esplicite per strumento: quantity_step, fixed_fee_eur, commission_bps,
fx_fee_bps, anche per costi nulli. Un basis point e 1/10000 del controvalore EUR.
Costi inclusi nel budget. Quantita al passo inferiore, mai oltre la tranche.
I1 ingresso iniziale; I2 terzi a gennaio/febbraio/marzo, resto dei centesimi
nell'ultima tranche; I3 liquidita a rendimento ipotetico zero.
Riserva, tranche future e residui distinti; residui non riutilizzati, niente
ribilanciamento o vendite. Riconciliazione cassa/acquisti con tolleranza 1e-30 EUR.
Rendimento e drawdown sono FRAZIONI, non percentuali. Drawdown solo sulle
osservazioni fornite piu capitale pre-ingresso, non intraday. Una singola
osservazione investita restituisce drawdown null.

## Confronto A/B/C

comparison.compare valida capitale, cutoff e struttura dei portafogli.
Genera 6 casi base, 6 controlli senza Shin-Etsu e un unico cash_I3 condiviso.
I controlli spostano soltanto il budget ShinEtsu nella riserva, senza
redistribuirlo sugli altri titoli. Tutti i casi usano lo stesso percorso.
Lo snapshot degli input e una copia indipendente. Nessuna classifica o probabilita.
L'esempio JSON allegato contiene prezzi, cambi, date, costi e frazioni TUTTI
sintetici: non condizioni del broker o dati acquisiti. I budget vengono dal mandato.

Esempio dal repository con pacchetto installato o PYTHONPATH=src:

```python
import json
from analisti_2027.comparison import compare
x = json.load(open('examples/scenario_sintetico.json'))
r = compare(x['mandate'], x['timeline'], x['entries'], x['rules'], data_kind=x['data_kind'])
```

## Collegamento CrewAI opzionale e separato

synthetic_bridge.build_synthetic_crew riceve gli stessi input e un LLM esplicito.
Costruisce una crew separata con un solo agente lettore, nessuno strumento o
delega. NON integra i sei agenti preesistenti e NON chiama kickoff.
Restituisce (crew, payload_numerico): il JSON deterministico e separato dal
commento eventualmente prodotto dal modello. Il commento non e una fonte
numerica validata e non ha un validatore semantico automatico.
Import CrewAI differito alla costruzione reale. Nessuna chiamata LLM o AMP
eseguita. I tre test del bridge usano componenti sostitutivi: NON provano la
compatibilita runtime. Smoke test reale e verifica della narrativa restano aperti.

## Test e limiti

python -m unittest discover -s tests -p 'test_*.py' -v

64 test locali: 42 invariati, 10 regressioni, 9 confronto e 3 contratto bridge.
Una regressione confronta 27 combinazioni con un calcolo indipendente Fraction;
queste combinazioni non sono conteggiate come 27 test separati.
Fonti reali, dividendi, split, liquidazione, imposte, benchmark total return,
calendari mercati e previsioni non implementati. financially_validated=false.
Nessuna build wheel, CI remota, deployment o esecuzione reale CrewAI effettuata.

# Report vincolato al mandato: ambito e provenienza

Base: e929e33. Modifica proposta su fix/mandate-bound-report, non ancora salvata.
Nessuna modifica al mandato, al simulatore, alle dipendenze o al modello.

## Assemblaggio
L'hook after_kickoff passa la bozza a bind_report e poi al quality gate esistente.
Prima dell'assemblaggio la bozza deve gia superare i controlli strutturali: non
si aggiungono marcatori mancanti e non si riparano link segnaposto o troncamenti.
Le sezioni 3 e 7 sono generate dal JSON del mandato: capitale totale, cutoff,
tabella A/B/C, controlli che sostituiscono solo Shin-Etsu e I1/I2/I3.
La sezione 9 e un piano prudenziale entro il cutoff, non una richiesta di dati futuri.
Se il registro delle evidenze e vuoto o assente, anche 1/2/4/5 usano modelli
prudenziali; URL estratti soltanto dai materiali forniti, NON fonti acquisite.
Non si mantengono tesi aziendali inventate per riempire la mancanza di evidenze.
Con evidenze registrate, 1/2/4/5 restano testo degli agenti da revisionare;
H1/H2/H10 nella scheda societaria vengono comunque rifiutati.
Scenari (6) e obiezioni (8) rimangono testo LLM. Non sono semanticamente certificati.
Il controllo sulle associazioni A/B/C-azienda copre il formato della regressione,
non ogni parafrasi possibile. Il limite di 800 parole resta attivo sul risultato.

## Conservazione e visibilita
Il risultato originale non viene mutato: si restituisce una copia, aggiornando
raw e raw dell'ultimo task della copia. Le tracce gia emesse possono mostrare
la bozza LLM, distinta dal report finale assemblato. Gli output strutturati
Pydantic/JSON non sono supportati e vengono rifiutati esplicitamente.
Per ogni assemblaggio accettato si scrive output/report_audits/<uuid>.json con
bozza, finale, esiti audit, sezioni sostituite e hash del mandato. Nei log appare
REPORT_BINDING_AUDIT con il percorso. Questi sono file nel runtime: persistenza
e disponibilita al download su AMP NON garantite da questa modifica.
financially_validated resta false. Gli artefatti possono contenere il report:
applicare una politica di conservazione se in futuro si introducono dati personali.

## Verifiche
16 nuovi test offline passati localmente su fixture sintetiche e oggetti
SimpleNamespace; controllo di sintassi del collegamento after_kickoff.
Suite completa, build e import con dipendenze reali da eseguire nella CI della PR.
Nessun kickoff reale, costo LLM, deployment o test del runtime enterprise eseguito.
La simulazione numerica A/B/C resta separata e non viene avviata dal renderer.

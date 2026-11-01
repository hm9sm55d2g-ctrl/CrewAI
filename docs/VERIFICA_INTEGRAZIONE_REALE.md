# Verifica del percorso numerico reale

Il commit iniziale della PR #6 ha quality=failure e runtime-import=skipped.
Il codice presenta due regressioni identificabili: il test di import cerca
check_output in crew.py dopo la delega a finish, e la fixture knowledge e
presente solo nel pacchetto, violando la sincronizzazione root/pacchetto.
Questa correzione aggiorna il test d'import e copia la fixture identica in root.

Otto nuovi test chiamano prepare, comparison/simulation, bind_report, finish e
quality gate reali, senza iniettare audit o motori sostitutivi. Verificano 13
casi piatti, 39 casi in tre scenari, costi, perdita e drawdown, tabella finale,
artefatto, percorso senza simulazione e rifiuto di input o fonti non validi.
La fixture del registro esiste solo nella directory temporanea dei test: il
revisore e human_verified sono valori sintetici per esercitare lo schema,
NON una revisione umana di dati reali e NON un registro distribuito.

Nella preparazione di questa correzione e stato eseguito solo il parsing AST
dei due file di test Python; gli otto nuovi test non sono stati eseguiti qui.
Devono passare nella suite CI prima di dichiarare verificato questo percorso.
I test usano SimpleNamespace come bozza/risultato: non provano oggetti CrewAI
reali, esecuzione dei sei agenti, hook nel runtime AMP, modelli o deployment.
Il test d'import continua a usare sostituti solo per isolare la sintassi degli
import, non per la matematica. I precedenti 12 test unitari restano invariati.
Nessun cambiamento a modello, mandato, motore o comportamento operativo.

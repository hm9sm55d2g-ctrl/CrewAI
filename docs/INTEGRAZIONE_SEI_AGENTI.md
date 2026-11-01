# Collegamento evidenze / sei agenti / motore sintetico

Questa modifica non acquisisce dati dal web, non inserisce nuove evidenze e non
trasforma il precedente report in un registro certificato. Modello, mandato,
quality gate e motore numerico restano invariati.

## Ingresso e calcoli
before_kickoff valida mandato e registro con il quality gate esistente prima
delle chiamate LLM. Il registro assente vale lista vuota: le schede restano ND.
I record richiedono snapshot UTF-8, hash, estratto, URL, data entro cutoff,
periodo/unita/valuta, revisore e human_verified=true. Non impostare quel campo
senza verifica umana effettiva. I materiali liberi non sono evidenze approvate.

scenario_bundle e un input opzionale del kickoff (oggetto JSON o stringa JSON).
In assenza si cerca knowledge/scenario_bundle.json; se manca non si simula.
La struttura contiene data_kind=synthetic e scenarios con H1/H2/H10 (anche un
sottoinsieme). Ogni scenario contiene assumptions, timeline, entries e rules.
I prezzi/cambi/costi ipotetici devono essere distinti dai dati societari reali.
Il motore originale valida date, quantita, costi e budget e produce 13 confronti
per scenario: A/B/C, relativi controlli senza Shin-Etsu, I1/I2 e I3 condiviso.
Non genera ipotesi dal bilancio e non supporta prezzi reali o backtest.

Il file scenario_bundle.example.json e una fixture piatta con prezzi e costi
inventati. NON viene caricato automaticamente, non rappresenta una tesi H1
reale e non documenta condizioni del broker. Per una prova tecnica copiare il
suo contenuto nell'input scenario_bundle. Non usarlo per decisioni finanziarie.

## Sei agenti e report
Ogni task riceve direttamente lo stesso dossier con record approvati, ipotesi
e tabella numerica; non dipende dalla sola memoria dei task precedenti.
I sei agenti interpretano questi dati senza ricalcolare i risultati. I calcoli
sono eseguiti prima degli agenti, NON decisi dai loro output. Questo e un
collegamento a ipotesi esplicite, non un agente che inventa autonomamente prezzi.
L'hook finale esegue il binder gia esistente e sostituisce la sezione 6 con una
tabella deterministica se esistono simulazioni. Non si conserva in quella
sezione la prosa degli scenari LLM: ipotesi complete e commenti intermedi restano
nel dossier e nelle tracce. Le altre sezioni sono ancora soggette ai limiti del
binder e alla revisione semantica. Non si garantisce assenza di ogni numero
inventato nella prosa: solo la tabella viene generata dal motore.
Il quality gate viene rieseguito sul risultato; limite 800 parole invariato,
nessun troncamento automatico. Output troppo lunghi vengono rifiutati.

## Tracciabilita e runtime
INTEGRATION_AUDIT segnala un JSON con contesto, input hash, risultati completi,
report dopo binder e report finale. L'artefatto del binder e precedente alla
sostituzione della sezione 6: usare quello di integrazione per il finale.
Persistenza e download su AMP non sono garantiti. financially_validated=false.
Usare una nuova istanza della crew per ogni kickoff: non condividere la stessa
istanza simultaneamente fra run. Nessuno strumento esterno o ordine al broker.

## Verifiche eseguite nella preparazione
12 test unitari dell'adapter con audit e motore iniettati; in locale le sole
costanti dei titoli/fine report sono sostituite da uno stub. Parsing AST dei tre
file Python riuscito. Non eseguiti suite completa, motore reale, test finish,
build, import CrewAI reale, kickoff, deployment o revisione di dati finanziari.
Questi controlli devono essere completati in CI prima del merge; in particolare
integrazione degli hook, identita dei numeri finali e confezionamento nel wheel.

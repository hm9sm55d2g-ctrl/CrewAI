# Progetto classico Python/YAML per CrewAI AMP

## Stato
Struttura proposta per AMP, non deployment eseguito o compatibilita runtime gia verificata. Riutilizza config/ e knowledge/ esistenti. Non modifica run.py o il workflow analisi.yml. README invariato.

## Struttura
- pyproject.toml: pacchetto, dipendenze e type crew.
- src/analisti_2027/crew.py: classe CrewBase, sei agenti e sei task decorati.
- src/analisti_2027/main.py: funzione run e avvio locale.
- .env.example: soli nomi e modello indicativo, nessuna chiave.
- config/ e knowledge/: fonti uniche gia presenti; incluse nel pacchetto wheel da Hatch.

## Passaggio obbligatorio: lock e verifica
La documentazione AMP richiede uv.lock. Non e incluso un lock inventato.
Dopo aver salvato i file, su GitHub aprire Actions > Prepara dipendenze CrewAI AMP > Run workflow sul ramo main.
Questo workflow, avviato SOLO manualmente, scarica dipendenze, esegue import e validazione input SENZA chiamare il modello e salva soltanto uv.lock in un nuovo commit. Ha contents: write per quel commit. Non ha push trigger o schedule.
Se installazione o import falliscono, non avviare il deployment: leggere il passo rosso. Se il ramo e protetto o i permessi negano il push, il lock non viene salvato; serve un percorso PR autorizzato.
In alternativa locale: uv lock; uv sync --locked; poi controllare import prima del test a pagamento.
La verifica di import NON e un test end-to-end del provider o del deployment AMP.

## Dashboard CrewAI
1. Collegare GitHub direttamente a CrewAI AMP e autorizzare hm9sm55d2g-ctrl/CrewAI.
2. Scegliere ramo main e directory radice, non src/analisti_2027.
3. Nelle variabili/segreti del deployment inserire OPENAI_API_KEY e CREW_MODEL con modello disponibile sul proprio account.
4. La chiave salvata su GitHub Actions non e automaticamente trasferita ad AMP. Non inviarla in chat.
5. Dopo lock e verifica, avviare Deploy e controllare build/log. Non attivare pianificazioni.
6. Un primo run del team comporta chiamate API e possibili costi. Controllare credito e modello prima di Trigger Crew.

## Input e risultati
Il progetto usa mandato ed evidenze nel repository tramite hook before_kickoff. Il mandato locale prevale su eventuali campi omonimi inviati dalla dashboard; per cambiare scenario aggiornare e versionare i materiali.
La funzione run restituisce CrewOutput e scrive una copia in output/. In AMP usare anche il risultato e le tracce dell'esecuzione; non presumere che il disco locale resti persistente tra run.

## Limiti
Solo analisi qualitativa, nessun feed live, browser, calcolatore finanziario o broker. I dati attuali sono mancanti. Nessun rendimento va inventato. Il limite informativo resta 2026-10-27 anche se il run avviene dopo. Le istruzioni nei prompt non garantiscono correttezza: revisione umana prima di decisioni. Nessun ordine, pagamento o accesso al conto. Budget tecnologico separato dai 3000 EUR.
Dipendenze >=1.15,<2 per CrewAI: il lock deve risolverle e il runner verificarle; se non disponibile una combinazione valida, correggere esplicitamente le versioni. Non promettere deployment finche non riuscito.

## Fonti tecniche consultate
https://docs-platform.crewai.com/platform/en/guides/prepare-for-deployment
https://docs-platform.crewai.com/platform/en/guides/deploy-to-amp

# Avvio del progetto 2027

## Prima esecuzione: nessuna API
Actions > CrewAI - controllo e analisi manuale > Run workflow > mode check.
Il workflow non parte su push e non ha schedule. La modalita check verifica configurazioni e budget; non testa il runtime CrewAI o i dati finanziari. Scaricare il risultato da Artifacts.

## Analisi: richiede provider e puo generare costi
Settings > Secrets and variables > Actions: aggiungere Secret OPENAI_API_KEY e Variable CREW_MODEL con un modello realmente disponibile, ad esempio nel formato openai/IDENTIFICATORE_REALE. Non inserire il segnaposto letteralmente. Non condividere la chiave. Poi scegliere mode analysis solo dopo aver controllato il costo presso il provider. Il timeout e max_iter non sono limiti monetari garantiti.

## Cosa fa questa versione
Sei agenti su materiali forniti, nessun browser, nessun feed live, nessun calcolatore finanziario e nessun broker. Con evidenze mancanti produce lacune e confronto qualitativo, non rendimenti. Le regole nei prompt non garantiscono correttezza fattuale: revisione umana obbligatoria prima di uso decisionale. Nessuna approvazione umana interattiva dentro il workflow e implementata.

## Dati e aggiornamenti
Inserire in knowledge/evidenze.txt soltanto dati pubblicabili con fonte/data/periodo/valuta. Questa repository e pubblica: niente informazioni personali o documenti riservati. Il limite informativo resta 2026-10-27: per aggiornare creare una versione distinta, non contaminare quella congelata.

## Riproducibilita e limiti
Dipendenze inizialmente non fissate. Dopo test riuscito registrare e fissare le versioni; installed-versions.txt accompagna ogni esecuzione riuscita. L'installazione e l'esecuzione CrewAI devono essere verificate nel runner. Non dichiarare questo progetto gia testato sul provider. Nessuna esecuzione o spesa API avviene soltanto aggiungendo questi file. Artifact e log possono essere accessibili: non inserire dati riservati.

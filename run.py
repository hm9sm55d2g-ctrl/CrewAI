import argparse
import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent

def load_inputs():
    mandate = json.loads((BASE / 'knowledge/mandato.json').read_text(encoding='utf-8'))
    agents = yaml.safe_load((BASE / 'config/agents.yaml').read_text(encoding='utf-8'))
    tasks = yaml.safe_load((BASE / 'config/tasks.yaml').read_text(encoding='utf-8'))
    evidence = (BASE / 'knowledge/evidenze.txt').read_text(encoding='utf-8').strip()
    if not evidence:
        raise ValueError('Registro evidenze vuoto')
    if mandate['capital_eur'] != 3000:
        raise ValueError('Capitale inatteso')
    for name, portfolio in mandate['portfolios'].items():
        if any(v < 0 for v in portfolio.values()) or sum(portfolio.values()) != 3000:
            raise ValueError(f'Budget non valido: {name}')
    if len(agents) != 6 or len(tasks) != 6:
        raise ValueError('Attesi sei agenti e sei task')
    for task in tasks.values():
        if task['agent'] not in agents:
            raise ValueError('Agente task non trovato')
    return mandate, agents, tasks, evidence

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['check', 'analysis'], default='check')
    args = parser.parse_args()
    load_dotenv(BASE / '.env')
    mandate, agent_config, task_config, evidence = load_inputs()
    out = BASE / 'output'
    out.mkdir(exist_ok=True)
    if args.mode == 'check':
        (out / 'controlli.md').write_text(
            '# Controllo locale superato\n\nBudget e configurazioni coerenti. Nessuna chiamata API. Nessuna verifica dei dati finanziari o compatibilita runtime CrewAI eseguita.\n',
            encoding='utf-8')
        print('Controlli superati. Nessuna chiamata API.')
        return
    key = os.getenv('OPENAI_API_KEY', '').strip()
    model = os.getenv('CREW_MODEL', '').strip()
    if not key or not model or 'INSERISCI' in model or 'NOME_ESATTO' in model:
        raise ValueError('Configurare OPENAI_API_KEY e CREW_MODEL')
    from crewai import Agent, Crew, LLM, Process, Task
    llm = LLM(model=model, temperature=0.2, max_tokens=2200)
    agents = {name: Agent(config=config, llm=llm, allow_delegation=False,
                          max_iter=4, verbose=False)
              for name, config in agent_config.items()}
    tasks = []
    for raw in task_config.values():
        config = dict(raw)
        agent_name = config.pop('agent')
        task = Task(config=config, agent=agents[agent_name], context=list(tasks))
        tasks.append(task)
    crew = Crew(agents=list(agents.values()), tasks=tasks,
                process=Process.sequential, memory=False, verbose=False)
    result = crew.kickoff(inputs={
        'mandato': json.dumps(mandate, ensure_ascii=False),
        'evidenze': evidence,
    })
    (out / 'report_preliminare.md').write_text(
        '# ANALISI PRELIMINARE NON VALIDATA\n\n' + result.raw, encoding='utf-8')
    metadata = {'information_cutoff': mandate['information_cutoff'],
                'model': model, 'mode': 'analysis', 'financial_calculator': False,
                'live_data_tools': False, 'orders_enabled': False}
    (out / 'run_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print('Report preliminare salvato. Nessun ordine eseguito.')

if __name__ == '__main__':
    main()

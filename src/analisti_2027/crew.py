import json
import os
from pathlib import Path

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, before_kickoff, after_kickoff, crew, task
from analisti_2027.report_contract import bind_report
from analisti_2027.integration import prepare, agent_context, task_config, finish

PACKAGE = Path(__file__).resolve().parent
RESOURCE_ROOT = PACKAGE if (PACKAGE / "config/agents.yaml").is_file() else PACKAGE.parents[1]


def project_inputs():
    mandate = json.loads((RESOURCE_ROOT / "knowledge/mandato.json").read_text(encoding="utf-8"))
    evidence = (RESOURCE_ROOT / "knowledge/evidenze.txt").read_text(encoding="utf-8").strip()
    if mandate.get("capital_eur") != 3000:
        raise ValueError("Capitale diverso da 3000 EUR")
    for name, values in mandate["portfolios"].items():
        if any(v < 0 for v in values.values()) or sum(values.values()) != 3000:
            raise ValueError(f"Budget incoerente: {name}")
    if not evidence:
        raise ValueError("Materiali evidenze vuoti")
    return {"mandato": json.dumps(mandate, ensure_ascii=False), "evidenze": evidence}


@CrewBase
class Analisti2027:
    """Six qualitative agents with explicit, offline synthetic calculations."""
    agents_config = str(RESOURCE_ROOT / "config/agents.yaml")
    tasks_config = str(RESOURCE_ROOT / "config/tasks.yaml")

    @before_kickoff
    def prepare_inputs(self, inputs):
        prepared = dict(inputs or {})
        self._integration_context = None
        context = prepare(RESOURCE_ROOT, prepared.pop("scenario_bundle", None))
        prepared.update(project_inputs())
        prepared["integration_context"] = agent_context(context)
        self._integration_context = context
        return prepared

    @after_kickoff
    def validate_final_output(self, result):
        context = getattr(self, "_integration_context", None)
        if context is None:
            raise ValueError("MISSING_INTEGRATION_CONTEXT")
        return finish(bind_report(result, RESOURCE_ROOT), context, RESOURCE_ROOT)

    def _config(self, name):
        return task_config(self.tasks_config[name], name)

    def _agent(self, name):
        model = os.getenv("CREW_MODEL", "").strip()
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not model or not key or "INSERISCI" in model or "IDENTIFICATORE" in model:
            raise ValueError("Configurare CREW_MODEL e OPENAI_API_KEY nel deployment AMP")
        llm = LLM(model=model, temperature=0.2, max_tokens=2200)
        return Agent(config=self.agents_config[name], llm=llm,
                     allow_delegation=False, max_iter=4, verbose=False)

    @agent
    def dati(self) -> Agent:
        return self._agent("dati")

    @agent
    def tecnologia(self) -> Agent:
        return self._agent("tecnologia")

    @agent
    def materiali(self) -> Agent:
        return self._agent("materiali")

    @agent
    def scenari(self) -> Agent:
        return self._agent("scenari")

    @agent
    def rischi(self) -> Agent:
        return self._agent("rischi")

    @agent
    def report(self) -> Agent:
        return self._agent("report")

    @task
    def validazione(self) -> Task:
        return Task(config=self._config("validazione"))

    @task
    def analisi_tecnologia(self) -> Task:
        return Task(config=self._config("tecnologia"), context=[self.validazione()])

    @task
    def analisi_materiali(self) -> Task:
        return Task(config=self._config("materiali"), context=[self.validazione()])

    @task
    def analisi_scenari(self) -> Task:
        return Task(config=self._config("scenari"), context=[
            self.validazione(), self.analisi_tecnologia(), self.analisi_materiali()])

    @task
    def revisione(self) -> Task:
        return Task(config=self._config("revisione"), context=[
            self.validazione(), self.analisi_tecnologia(), self.analisi_materiali(), self.analisi_scenari()])

    @task
    def report_finale(self) -> Task:
        return Task(config=self._config("report"), context=[
            self.validazione(), self.analisi_tecnologia(), self.analisi_materiali(),
            self.analisi_scenari(), self.revisione()])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks,
                    process=Process.sequential, memory=False, verbose=False)

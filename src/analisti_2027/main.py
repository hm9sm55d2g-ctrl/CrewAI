from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from analisti_2027.crew import Analisti2027, project_inputs


def run():
    """Entry point classico CrewAI: una esecuzione comporta chiamate API."""
    load_dotenv()
    inputs = project_inputs()
    result = Analisti2027().crew().kickoff(inputs=inputs)
    output = Path("output")
    output.mkdir(exist_ok=True)
    path = output / f"report_amp_{uuid4().hex}.md"
    path.write_text("# ANALISI PRELIMINARE NON VALIDATA\n\n" + result.raw, encoding="utf-8")
    print(f"Report preliminare scritto: {path.name}")
    return result


if __name__ == "__main__":
    run()

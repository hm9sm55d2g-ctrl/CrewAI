"""Real-dependency import and crew construction smoke test; no network or kickoff."""
from contextlib import ExitStack
import importlib
import importlib.util
import json
from importlib.metadata import version
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch


def check_resources(module):
    root = Path(module.RESOURCE_ROOT)
    for name in ("config/agents.yaml", "config/tasks.yaml", "knowledge/mandato.json", "knowledge/evidenze.txt"):
        path = root / name
        if not path.is_file() or not path.read_bytes():
            raise RuntimeError("Missing or empty resource: " + str(path))
    inputs = module.project_inputs()
    if json.loads(inputs["mandato"])["capital_eur"] != 3000 or not inputs["evidenze"].strip():
        raise RuntimeError("Invalid project inputs")
    for name in ("bind_report", "prepare", "agent_context", "finish"):
        if not callable(getattr(module, name, None)):
            raise RuntimeError("Integration entry point not callable: " + name)
    quality = importlib.import_module("analisti_2027.quality")
    if not callable(getattr(quality, "check_output", None)):
        raise RuntimeError("Quality gate not callable")


def check_construction(module):
    instance = module.Analisti2027()
    built = instance.crew()
    if len(built.agents) != 6 or len(built.tasks) != 6:
        raise RuntimeError("Expected exactly six agents and six tasks")
    expected = ("validazione", "tecnologia", "materiali", "scenari", "revisione", "report")
    for name, task in zip(expected, built.tasks):
        if not any(task.agent is agent for agent in built.agents):
            raise RuntimeError("Task agent identity not preserved: " + name)
        if "DOSSIER JSON:\n{integration_context}" not in task.description:
            raise RuntimeError("Missing integration context: " + name)
        if task.description != instance._config(name)["description"]:
            raise RuntimeError("Unexpected task description: " + name)
    if instance.validazione() is not built.tasks[0]:
        raise RuntimeError("Task memoization identity not preserved")


def loose_import(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot create module spec")
    module = importlib.util.module_from_spec(spec)
    if module.__package__:
        raise RuntimeError("Test must load without a parent package")
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        check_resources(module)
        check_construction(module)
    finally:
        sys.modules.pop(name, None)


def forbidden(*args, **kwargs):
    raise RuntimeError("Network and kickoff are forbidden in this smoke test")


def main():
    with ExitStack() as guards:
        guards.enter_context(patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-offline-smoke-test-not-a-real-key",
            "CREW_MODEL": "gpt-4o-mini",
            "OTEL_SDK_DISABLED": "true",
            "CREWAI_TRACING_ENABLED": "false",
        }))
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.create_connection", "socket.getaddrinfo"):
            guards.enter_context(patch(target, side_effect=forbidden))
        from crewai import Crew
        guards.enter_context(patch.object(Crew, "kickoff", side_effect=forbidden))
        guards.enter_context(patch.object(Crew, "akickoff", side_effect=forbidden))
        installed = importlib.import_module("analisti_2027.crew")
        installed_path = Path(installed.__file__).resolve()
        if not installed_path.is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError("Expected installed wheel, not editable/source package: " + str(installed_path))
        check_resources(installed)
        check_construction(installed)
        loose_import(installed_path, "amp_installed_crew_smoke")
        checkout = Path(__file__).resolve().parents[1]
        loose_import(checkout / "src/analisti_2027/crew.py", "amp_source_crew_smoke")
        print(json.dumps({"status": "passed", "python": sys.version.split()[0], "crewai": version("crewai"),
                          "checks": ["installed_package_import", "installed_loose_import", "source_loose_import", "resources_and_inputs", "integration_entry_points", "quality_gate_import", "six_agents_and_tasks_construction_in_all_modes", "task_agent_identity", "task_description_and_memoization"],
                          "network_blocked": True, "kickoff_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()

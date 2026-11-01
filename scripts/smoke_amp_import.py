"""Real-dependency import smoke test. No Agent construction or kickoff."""
import importlib
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path
import sys


def check_resources(module):
    root = Path(module.RESOURCE_ROOT)
    for name in ("config/agents.yaml", "config/tasks.yaml", "knowledge/mandato.json", "knowledge/evidenze.txt"):
        path = root / name
        if not path.is_file() or not path.read_bytes():
            raise RuntimeError("Missing or empty resource: " + str(path))
    inputs = module.project_inputs()
    if json.loads(inputs["mandato"])["capital_eur"] != 3000 or not inputs["evidenze"].strip():
        raise RuntimeError("Invalid project inputs")
    if not callable(module.check_output):
        raise RuntimeError("Quality gate not callable")


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
    finally:
        sys.modules.pop(name, None)


def main():
    installed = importlib.import_module("analisti_2027.crew")
    installed_path = Path(installed.__file__).resolve()
    if not installed_path.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Expected installed wheel, not editable/source package: " + str(installed_path))
    check_resources(installed)
    loose_import(installed_path, "amp_installed_crew_smoke")
    checkout = Path(__file__).resolve().parents[1]
    loose_import(checkout / "src/analisti_2027/crew.py", "amp_source_crew_smoke")
    print(json.dumps({"status": "passed", "python": sys.version.split()[0], "crewai": version("crewai"),
                      "checks": ["installed_package_import", "installed_loose_import", "source_loose_import", "resources_and_inputs"],
                      "kickoff_executed": False}, sort_keys=True))


if __name__ == "__main__":
    main()

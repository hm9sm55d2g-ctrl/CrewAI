"""Exercise actual CrewBase callbacks and kickoff methods; replace only task execution."""
import asyncio
from contextlib import ExitStack, redirect_stdout
import hashlib
from importlib.metadata import version
from io import StringIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def forbidden(*args, **kwargs):
    raise AssertionError('NETWORK_OR_LLM_CALL_FORBIDDEN')


def run_case(module, mode, rejected):
    from crewai import Task
    from crewai.tasks.task_output import TaskOutput
    from analisti_2027.quality import SECTIONS, END

    raw = '# ANALISI PRELIMINARE NON VALIDATA\n\n' + '\n\n'.join(
        '## ' + name + '\nND: fixture tecnica senza evidenze acquisite.' for name in SECTIONS
    ) + '\n\n' + END
    if rejected:
        raw = raw.replace('# ANALISI PRELIMINARE NON VALIDATA', '### ANALISI PRELIMINARE NON VALIDATA', 1)
    events = []
    executed = []
    original_bind = module.bind_report
    original_finish = module.finish
    with TemporaryDirectory() as directory:
        root = Path(directory)

        def task_result(task, *args, **kwargs):
            executed.append(str(task.id))
            output = TaskOutput(description=task.description, expected_output=task.expected_output,
                                agent=task.agent.role, raw=raw)
            task.output = output
            return output

        async def async_task_result(task, *args, **kwargs):
            return task_result(task, *args, **kwargs)

        def binding(result, resource_root, *, as_of):
            events.append({'stage': 'binder_enter', 'sha256': digest(result.raw)})
            try:
                bound = original_bind(result, resource_root, root / 'binding', as_of=as_of)
            except Exception as exc:
                events.append({'stage': 'binder_error', 'error_type': type(exc).__name__, 'error': str(exc)})
                raise
            events.append({'stage': 'binder_exit', 'sha256': digest(bound.raw),
                           'new_object': bound is not result})
            return bound

        def finishing(result, context, resource_root):
            events.append({'stage': 'finish_enter', 'sha256': digest(result.raw)})
            final = original_finish(result, context, resource_root, root / 'integration')
            events.append({'stage': 'finish_exit', 'sha256': digest(final.raw)})
            return final

        with ExitStack() as guards:
            guards.enter_context(patch.object(Task, 'execute_sync', task_result))
            guards.enter_context(patch.object(Task, 'aexecute_sync', async_task_result))
            guards.enter_context(patch.object(module, 'bind_report', binding))
            guards.enter_context(patch.object(module, 'finish', finishing))
            instance = module.Analisti2027()
            built = instance.crew()
            assert len(built.agents) == 6 and len(built.tasks) == 6
            assert len(built.before_kickoff_callbacks) == 1, 'BEFORE_HOOK_NOT_REGISTERED_ONCE'
            assert len(built.after_kickoff_callbacks) == 1, 'AFTER_HOOK_NOT_REGISTERED_ONCE'
            observed_error = None
            returned = None
            try:
                if mode == 'sync':
                    returned = built.kickoff(inputs={})
                else:
                    returned = asyncio.run(built.akickoff(inputs={}))
            except ValueError as exc:
                observed_error = str(exc)
            assert len(executed) == 6, ('UNEXPECTED_TASK_EXECUTION_COUNT', len(executed))
            assert getattr(instance, '_integration_context', None) is not None, 'BEFORE_HOOK_CONTEXT_MISSING'
            assert sum(e['stage'] == 'binder_enter' for e in events) == 1, 'BINDER_NOT_CALLED_ONCE'
            diagnostic = {'mode': mode, 'rejected_fixture': rejected, 'events': events,
                          'task_count': len(executed), 'error': observed_error,
                          'callback_names': [getattr(c, '__name__', type(c).__name__) for c in built.after_kickoff_callbacks]}
            if rejected:
                assert observed_error and 'DRAFT_STRUCTURE_FAILED' in observed_error, 'REJECTION_NOT_PROPAGATED'
                assert not any(e['stage'] == 'finish_enter' for e in events), 'FINISH_EXECUTED_AFTER_REJECTION'
                saved = json.loads(next((root / 'binding').glob('*.json')).read_text(encoding='utf-8'))
                assert saved['draft_raw'] == raw and saved['status'] == 'draft_rejected'
            else:
                assert observed_error is None, observed_error
                assert returned is not None, 'MISSING_RETURNED_OUTPUT'
                final_events = [e for e in events if e['stage'] == 'finish_exit']
                assert len(final_events) == 1, 'FINISH_NOT_CALLED_ONCE'
                diagnostic['returned_sha256'] = digest(returned.raw)
                assert digest(returned.raw) == final_events[0]['sha256'], 'AFTER_HOOK_RETURN_NOT_ADOPTED'
                assert returned.raw != raw, 'ORIGINAL_DRAFT_RETURNED'
                assert '|A|750|600|600|450|600|3000|' in returned.raw
                assert returned.tasks_output[-1].raw == returned.raw, 'RETURNED_TASK_OUTPUT_MISMATCH'
                saved = json.loads(next((root / 'integration').glob('*.json')).read_text(encoding='utf-8'))
                assert saved['final_report'] == returned.raw, 'AUDIT_RETURN_MISMATCH'
                cached = getattr(built, 'output', None)
                diagnostic['crew_output_sha256'] = digest(cached.raw) if cached is not None else None
                diagnostic['crew_output_matches_returned'] = cached is not None and cached.raw == returned.raw
                diagnostic['original_task_output_sha256'] = digest(built.tasks[-1].output.raw)
            diagnostic['status'] = 'passed'
            return diagnostic


def main():
    report = {'cases': [], 'network_blocked': True, 'llm_calls_allowed': False,
              'scope': 'Open-source CrewAI runtime only; not Enterprise AMP persistence or UI'}
    destination = Path('output/hook-lifecycle.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    failed = False
    capture = StringIO()
    try:
        with ExitStack() as guards:
            guards.enter_context(patch.dict(os.environ, {
                'OPENAI_API_KEY': 'sk-offline-test-not-a-real-key', 'CREW_MODEL': 'gpt-4o-mini',
                'OTEL_SDK_DISABLED': 'true', 'CREWAI_TRACING_ENABLED': 'false',
            }))
            for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                           'socket.create_connection', 'socket.getaddrinfo'):
                guards.enter_context(patch(target, side_effect=forbidden))
            from crewai import LLM
            guards.enter_context(patch.object(LLM, 'call', side_effect=forbidden))
            guards.enter_context(patch.object(LLM, 'acall', side_effect=forbidden))
            import analisti_2027.crew as module
            report['crewai_version'] = version('crewai')
            report['python'] = sys.version.split()[0]
            for mode in ('sync', 'async'):
                for rejected in (False, True):
                    try:
                        with redirect_stdout(capture):
                            case = run_case(module, mode, rejected)
                        report['cases'].append(case)
                    except Exception as exc:
                        failed = True
                        report['cases'].append({'mode': mode, 'rejected_fixture': rejected,
                                                'status': 'failed', 'error_type': type(exc).__name__, 'error': str(exc)})
    except Exception as exc:
        failed = True
        report['setup_error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        report['status'] = 'failed' if failed else 'passed'
        report['captured_audit_lines'] = [line for line in capture.getvalue().splitlines()
                                          if line.startswith(('REPORT_BINDING_AUDIT ', 'QUALITY_AUDIT ', 'INTEGRATION_AUDIT '))]
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

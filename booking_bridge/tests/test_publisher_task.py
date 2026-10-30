"""Check a dormant Windows deployment artifact without installing any task."""
import ctypes
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from booking_bridge.model import HOME


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows task preparation helper')
HELPER = HOME / 'deploy' / 'prepare_publisher_task.ps1'
NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def invoke(tmp_path, output_name='prepared.xml'):
    workspace = tmp_path / 'local & spaced workspace'
    python = workspace / '.venv' / 'Scripts' / 'python.exe'
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('This fixture must never execute.')
    config, env, state = (workspace / 'profile & trial.json', workspace / 'private.env',
                          workspace / 'state directory')
    config.write_text('not-json: preparation checks paths only')
    env.write_text('DO_NOT_READ_OR_EXPORT_SECRET=secret-marker')
    state.mkdir(exist_ok=True)
    output = tmp_path / output_name
    result = subprocess.run([
        'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(HELPER),
        '-Workspace', str(workspace), '-Config', str(config), '-State', str(state) + '\\',
        '-EnvFile', str(env), '-Output', str(output),
    ], capture_output=True, text=True, timeout=30)
    return result, output, workspace, python, config, env, state


def windows_argv(command):
    count = ctypes.c_int()
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = split(command, ctypes.byref(count))
    if not argv:
        raise ctypes.WinError()
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(argv)


def test_prepared_task_remains_disabled_and_paths_roundtrip_without_a_shell(tmp_path):
    result, output, workspace, python, config, env, state = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    body = output.read_text(encoding='utf-8')
    assert 'secret-marker' not in body + result.stdout + result.stderr
    task = ET.fromstring(body)
    def value(path):
        return task.find(path, NS).text
    assert value('t:Settings/t:Enabled') == 'false'
    assert value('t:Triggers/t:LogonTrigger/t:Enabled') == 'false'
    assert value('t:Principals/t:Principal/t:LogonType') == 'InteractiveToken'
    assert value('t:Principals/t:Principal/t:RunLevel') == 'LeastPrivilege'
    assert value('t:Principals/t:Principal/t:UserId') == value('t:Triggers/t:LogonTrigger/t:UserId')
    assert value('t:Settings/t:MultipleInstancesPolicy') == 'IgnoreNew'
    assert value('t:Settings/t:ExecutionTimeLimit') == 'PT0S'
    assert value('t:Settings/t:RestartOnFailure/t:Interval') == 'PT5M'
    assert value('t:Settings/t:RestartOnFailure/t:Count') == '3'
    assert value('t:Actions/t:Exec/t:Command') == str(python)
    assert value('t:Actions/t:Exec/t:WorkingDirectory') == str(workspace)
    argv = windows_argv('python.exe ' + value('t:Actions/t:Exec/t:Arguments'))
    assert argv[:7] == ['python.exe', '-m', 'booking_bridge.pilot_supervisor', '--run',
                       '--read-only', '--config', str(config)]
    assert Path(argv[argv.index('--state') + 1]) == state
    assert argv[argv.index('--env-file') + 1] == str(env)


def test_preparation_refuses_to_overwrite_existing_output(tmp_path):
    output = tmp_path / 'existing.xml'
    output.write_text('already-reviewed-task')
    result, *_ = invoke(tmp_path, output.name)
    assert result.returncode != 0
    assert output.read_text() == 'already-reviewed-task'

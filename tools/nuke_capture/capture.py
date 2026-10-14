import ctypes
import argparse
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

class STARTUPINFO(ctypes.Structure):
    _fields_ = [('cb', W.DWORD), ('lpReserved', W.LPWSTR), ('lpDesktop', W.LPWSTR),
        ('lpTitle', W.LPWSTR), ('dwX', W.DWORD), ('dwY', W.DWORD),
        ('dwXSize', W.DWORD), ('dwYSize', W.DWORD), ('dwXCountChars', W.DWORD),
        ('dwYCountChars', W.DWORD), ('dwFillAttribute', W.DWORD),
        ('dwFlags', W.DWORD), ('wShowWindow', W.WORD), ('cbReserved2', W.WORD),
        ('lpReserved2', ctypes.POINTER(ctypes.c_byte)), ('hStdInput', W.HANDLE),
        ('hStdOutput', W.HANDLE), ('hStdError', W.HANDLE)]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', W.HANDLE), ('hThread', W.HANDLE),
               ('dwProcessId', W.DWORD), ('dwThreadId', W.DWORD)]

def main():
    parser = argparse.ArgumentParser(description='Capture NukeX on an isolated Windows desktop.')
    parser.add_argument('--exe', default=r'C:\Program Files\Nuke17.1v2\Nuke17.1.exe')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--node', help='Create this node and open its properties in the disposable session.')
    parser.add_argument('--widget', help='Capture the uniquely named visible Qt widget.')
    parser.add_argument('--rect', nargs=4, type=int, metavar=('X','Y','WIDTH','HEIGHT'))
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--fixture', action='store_true', help='Build a checkerboard, grade, and viewer reference graph.')
    parser.add_argument('--atlas', action='store_true', help='Map menus, tabs, and representative node properties.')
    parser.add_argument('--size', nargs=2, type=int, default=[1600,1000], metavar=('WIDTH','HEIGHT'))
    args = parser.parse_args()
    root = (args.output or Path(__file__).resolve().parent / ('capture-' + uuid.uuid4().hex[:8])).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'request.json').write_text(json.dumps({'node':args.node,'widget':args.widget,'rect':args.rect,
        'fixture':args.fixture or args.atlas,'atlas':args.atlas,'size':args.size}))
    bootstrap = Path(__file__).resolve().parent
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.CreateDesktopW.argtypes = [W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, W.DWORD, W.DWORD, ctypes.c_void_p]
    user.CreateDesktopW.restype = W.HANDLE
    user.CloseDesktop.argtypes = [W.HANDLE]
    kernel.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD, ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
    kernel.CreateProcessW.restype = W.BOOL
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    desktop_name = 'AtomicCapture_' + uuid.uuid4().hex
    desktop = user.CreateDesktopW(desktop_name, None, None, 0, 0x01FF, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    env = dict(os.environ)
    env['ATOMIC_CAPTURE_ROOT'] = str(root)
    env['NUKE_PATH'] = str(bootstrap)
    (root / 'temp').mkdir()
    env['NUKE_TEMP_DIR'] = str(root / 'temp')


    block = ctypes.create_unicode_buffer('\0'.join(f'{k}={v}' for k,v in sorted(env.items())) + '\0\0')
    exe = args.exe
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([exe, '--nukex', '--safe', str(bootstrap / 'menu.py')]))
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = 'winsta0\\' + desktop_name
    pi = PROCESS_INFORMATION()
    try:
        if not kernel.CreateProcessW(exe, cmd, None, None, False, 0x400, block, str(root), ctypes.byref(si), ctypes.byref(pi)):
            raise ctypes.WinError(ctypes.get_last_error())
        print(json.dumps({'root':str(root), 'pid':pi.dwProcessId, 'desktop':desktop_name}), flush=True)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if (root / 'result.json').exists():
                result = json.loads((root / 'result.json').read_text())
                print(json.dumps(result,indent=2), flush=True)
                if not result.get('ok'):
                    raise RuntimeError('Capture failed; inspect result.json')
                break
            if kernel.WaitForSingleObject(pi.hProcess, 500) == 0:
                raise RuntimeError('Nuke exited before capture; inspect startup and licensing in the host context.')
        else:
            raise TimeoutError('Nuke capture timed out; no successful result was produced.')
    finally:
        if pi.hProcess:
            kernel.TerminateProcess(pi.hProcess, 0)
            kernel.WaitForSingleObject(pi.hProcess, 5000)
            kernel.CloseHandle(pi.hThread)
            kernel.CloseHandle(pi.hProcess)
        user.CloseDesktop(desktop)

if __name__ == '__main__':
    main()

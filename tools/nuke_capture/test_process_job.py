import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from capture import STARTUPINFO, PROCESS_INFORMATION
from process_job import ProcessJob


@unittest.skipUnless(os.name == 'nt', 'Windows process ownership')
class ProcessJobTests(unittest.TestCase):
    def test_closing_job_removes_orphan_child_and_preserves_unrelated_process(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            W.BOOL, W.DWORD, ctypes.c_void_p, W.LPCWSTR,
            ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
        kernel.CreateProcessW.restype = W.BOOL
        kernel.ResumeThread.argtypes = [W.HANDLE]
        kernel.ResumeThread.restype = W.DWORD
        kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        kernel.OpenProcess.restype = W.HANDLE
        kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        kernel.WaitForSingleObject.restype = W.DWORD
        kernel.CloseHandle.argtypes = [W.HANDLE]
        kernel.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=0x08000000)
        job = ProcessJob(); pi = PROCESS_INFORMATION(); child_handle = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                marker = Path(tmp)/'child.pid'
                code = ('import subprocess,sys; from pathlib import Path; '
                        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],creationflags=0x08000000); "
                        f'Path({str(marker)!r}).write_text(str(p.pid))')
                command = ctypes.create_unicode_buffer(subprocess.list2cmdline([sys.executable, '-c', code]))
                si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
                self.assertTrue(kernel.CreateProcessW(sys.executable,command,None,None,False,
                    0x08000004,None,tmp,ctypes.byref(si),ctypes.byref(pi)))
                job.assign(pi.hProcess)
                self.assertNotEqual(kernel.ResumeThread(pi.hThread),0xFFFFFFFF)
                deadline = time.monotonic()+10
                while not marker.exists() and time.monotonic()<deadline: time.sleep(0.05)
                self.assertTrue(marker.exists(), 'Child did not start')
                self.assertEqual(kernel.WaitForSingleObject(pi.hProcess,10000),0, 'Parent did not exit')
                child_handle = kernel.OpenProcess(0x00100000,False,int(marker.read_text()))
                self.assertTrue(child_handle)
                self.assertEqual(kernel.WaitForSingleObject(child_handle,0),258, 'Child should outlive parent')
                job.close()
                self.assertEqual(kernel.WaitForSingleObject(child_handle,5000),0, 'Orphan child survived job cleanup')
                self.assertIsNone(unrelated.poll(), 'Unrelated process was affected')
        finally:
            if pi.hProcess: kernel.TerminateProcess(pi.hProcess,0)
            job.close()
            for handle in [child_handle,pi.hThread,pi.hProcess]:
                if handle: kernel.CloseHandle(handle)
            unrelated.terminate(); unrelated.wait(timeout=5)


if __name__ == '__main__': unittest.main()

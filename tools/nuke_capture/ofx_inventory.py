"""Read shipped OFX identifiers through the standard discovery API."""
import ctypes
import json
import os
from pathlib import Path
import sys


class Plugin(ctypes.Structure):
    _fields_=[('api',ctypes.c_char_p),('api_version',ctypes.c_int),
              ('identifier',ctypes.c_char_p),('major',ctypes.c_uint),('minor',ctypes.c_uint),
              ('set_host',ctypes.c_void_p),('entry',ctypes.c_void_p)]


def discover(install):
    rows=[]
    with os.add_dll_directory(str(install)):
        for path in sorted((install/'plugins').glob('*.ofx.bundle/Contents/Win64/*.ofx')):
            with os.add_dll_directory(str(path.parent)):
                library=ctypes.CDLL(str(path))
                library.OfxGetNumberOfPlugins.restype=ctypes.c_int
                library.OfxGetPlugin.argtypes=[ctypes.c_int]
                library.OfxGetPlugin.restype=ctypes.POINTER(Plugin)
                count=library.OfxGetNumberOfPlugins()
                if not 0<=count<=10000: raise ValueError('Invalid OFX descriptor count')
                for index in range(count):
                    pointer=library.OfxGetPlugin(index)
                    if not pointer: raise ValueError('Missing OFX descriptor')
                    plugin=pointer.contents
                    rows.append({'identifier':plugin.identifier.decode(),'api':plugin.api.decode(),
                                 'version':[plugin.major,plugin.minor],'source':str(path)})
    return rows


if __name__=='__main__':
    rows=discover(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))

"""Enumerate shipped node candidates and capture one disposable node at a time."""
import ast
import hashlib
import json
from pathlib import Path
import traceback
import nuke
from PySide6 import QtCore, QtWidgets
from gpu_capture import capture_window, crop_widget
from ui_atlas import controls, slug


def write(path,data):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    temp.replace(path)


def enumerate_types():
    sources={}
    def add(name,source):
        sources.setdefault(name,[]).append(source)
    for name in nuke.nodeTypes(): add(name,'loaded registry')
    install=Path(nuke.EXE_PATH).parent
    for extension in ('*.dll','*.gizmo'):
        for path in (install/'plugins').glob(extension):
            add(path.stem,str(path))
    # Parse literal constructors from the shipped menu definitions, never execute
    # menu commands: some commands open browsers, dialogs, or launch workflows.
    source=install/'plugins'/'nukescripts'/'toolbars.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    for item in ast.walk(tree):
        if not isinstance(item,ast.Constant) or not isinstance(item.value,str): continue
        if 'createNode' not in item.value: continue
        try: code=ast.parse(item.value)
        except SyntaxError: continue
        for call in ast.walk(code):
            if (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                    and call.func.attr in ('createNode','createNodeLocal') and call.args
                    and isinstance(call.args[0],ast.Constant) and isinstance(call.args[0].value,str)):
                add(call.args[0].value,str(source)+':'+str(item.lineno))
    return {'version':nuke.NUKE_VERSION_STRING,'scope':'Loaded registry, shipped DLL/gizmo files, literal toolbar constructors; external OFX excluded',
            'candidates':[{'type':name,'sources':sorted(set(origins))} for name,origins in sorted(sources.items())]}


class NodeCatalog:
    def __init__(self,window,root,publish,limit):
        self.window,self.root,self.publish,self.limit=window,root,publish,limit
        self.node=None
        self.done=0

    def start(self):
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'nodes').mkdir(exist_ok=True)
        inventory=self.root/'inventory.json'
        if not inventory.exists(): write(inventory,enumerate_types())
        data=json.loads(inventory.read_text(encoding='utf-8'))
        if data['version']!=nuke.NUKE_VERSION_STRING: raise RuntimeError('Catalog Nuke version mismatch')
        self.pending=[r for r in data['candidates'] if not self.record_path(r['type']).exists()][:self.limit]
        self.next()

    def discover_loaded(self):
        path=self.root/'inventory.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        known={r['type'] for r in data['candidates']}
        extra=[{'type':name,'sources':['registry after loading '+self.row['type']]}
               for name in nuke.nodeTypes() if name not in known]
        if extra:
            data['candidates']=sorted(data['candidates']+extra,key=lambda r:r['type'])
            write(path,data)

    def record_path(self,name):
        return self.root/'nodes'/(slug(name)+'-'+hashlib.sha256(name.encode()).hexdigest()[:8]+'.json')

    def save(self):
        self.discover_loaded()
        write(self.record_path(self.row['type']),self.row)

    def next(self):
        if self.node is not None:
            self.node.hideControlPanel()
            nuke.delete(self.node)
            self.node=None
        if not self.pending:
            write(self.root/'current.json',{'state':'complete','processed':self.done})
            self.publish({'ok':True,'processed':self.done})
            return
        self.row=dict(self.pending.pop(0))
        name=self.row['type']
        write(self.root/'current.json',{'type':name,'state':'creating','processed':self.done})
        self.done+=1
        try:
            if not nuke.canCreateNode(name):
                self.row.update(status='unavailable',reason='nuke.canCreateNode returned False')
                self.save()
                QtCore.QTimer.singleShot(10,self.next)
                return
            self.node=getattr(nuke.nodes,name)()
            self.row['class']=self.node.Class()
            self.row['name']=self.node.name()
            self.node.setXYpos(0,0)
            nuke.zoom(1,[0,0])
            nuke.show(self.node)
            self.row['knobs']=[]
            for key,knob in self.node.knobs().items():
                record={'name':key,'label':knob.label(),'class':knob.Class(),'tooltip':knob.tooltip()}
                try: record['script']=knob.toScript()
                except Exception as e: record['error']=str(e)
                self.row['knobs'].append(record)
            QtCore.QTimer.singleShot(800,self.capture)
        except Exception:
            self.row.update(status='error',reason=traceback.format_exc())
            if 'plugin did not define ' in self.row['reason'] or 'Unknown command' in self.row['reason']:
                self.row['status']='not_node'
            self.save()
            QtCore.QTimer.singleShot(10,self.next)

    def capture(self):
        try:
            dialogs=[w for w in QtWidgets.QApplication.topLevelWidgets()
                     if w.isVisible() and isinstance(w,QtWidgets.QDialog)]
            if dialogs:
                self.row['dialogs']=[{'title':w.windowTitle(),'class':w.metaObject().className()} for w in dialogs]
                raise RuntimeError('Node opened a dialog; no dialog accepted')
            image,gpu=capture_window(self.window)
            self.row['images']={}
            for role,widget_name in [('properties','Properties.1'),('graph','DAG.1')]:
                found=[w for w in self.window.findChildren(QtWidgets.QWidget) if w.isVisible() and w.objectName()==widget_name]
                if len(found)!=1: raise RuntimeError('Expected one '+widget_name)
                cropped=crop_widget(image,self.window,found[0])
                path=self.record_path(self.row['type']).with_suffix('.'+role+'.png')
                if not cropped.save(str(path)): raise RuntimeError('PNG save failed')
                self.row['images'][role]={'file':path.name,'size':[cropped.width(),cropped.height()],
                                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            self.row.update(status='captured',gpu=gpu,controls=controls(self.window))
        except Exception:
            self.row.update(status='error',reason=traceback.format_exc())
        self.save()
        if self.row.get('dialogs'):
            self.publish({'ok':False,'error':'Node opened a dialog; restart before the next candidate','type':self.row['type']})
            return
        QtCore.QTimer.singleShot(10,self.next)

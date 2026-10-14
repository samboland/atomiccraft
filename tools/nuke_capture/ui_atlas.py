"""Repeatable, bounded exploration of the disposable NukeX reference session."""
import html
import json
import re
import traceback
from pathlib import Path
import nuke
from PySide6 import QtCore, QtGui, QtWidgets
from gpu_capture import capture_window, crop_widget


def slug(value):
    return re.sub(r'[^a-zA-Z0-9_-]+','-',value).strip('-') or 'unnamed'


def dump(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')


def controls(window):
    rows=[]
    for widget in window.findChildren(QtWidgets.QWidget):
        if not widget.isVisible():
            continue
        pos=widget.mapTo(window,QtCore.QPoint())
        row={'class':widget.metaObject().className(),'name':widget.objectName(),
             'title':widget.windowTitle(),'rect':[pos.x(),pos.y(),widget.width(),widget.height()],
             'enabled':widget.isEnabled(),'tooltip':widget.toolTip(),
             'accessible_name':widget.accessibleName()}
        if isinstance(widget,(QtWidgets.QAbstractButton,QtWidgets.QLabel,QtWidgets.QLineEdit)):
            row['text']=widget.text()
        if isinstance(widget,QtWidgets.QAbstractButton):
            row['checked']=widget.isChecked()
        if isinstance(widget,QtWidgets.QComboBox):
            row['items']=[widget.itemText(i) for i in range(widget.count())]
            row['current']=widget.currentText()
        if isinstance(widget,QtWidgets.QTabBar):
            row['tabs']=[widget.tabText(i) for i in range(widget.count())]
            row['current']=widget.currentIndex()
        rows.append(row)
    return rows


class Atlas:
    def __init__(self,window,root,publish,result):
        self.window,self.root,self.publish,self.result=window,root,publish,result
        self.directory=root/'atlas'
        self.directory.mkdir()
        self.entries=[]
        self.failures=[]
        self.jobs=[]
        self.current_node=None
        self.viewer_before=None
        self.verification={}
        self.qtmenus={}

    def snapshot(self,title,category,target=None):
        image,gpu=capture_window(self.window)
        target=target or self.window
        image=crop_widget(image,self.window,target)
        filename=f'{len(self.entries):03d}-{slug(title)}.png'
        if not image.save(str(self.directory/filename)):
            raise RuntimeError('Failed saving '+filename)
        data={'title':title,'category':category,'image':filename,
              'size':[image.width(),image.height()],'gpu':gpu,'controls':controls(self.window)}
        dump(self.directory/(Path(filename).stem+'.json'),data)
        self.entries.append({'title':title,'category':category,'image':filename,
                             'evidence':Path(filename).stem+'.json'})
        return gpu

    def target(self,name):
        found=[w for w in self.window.findChildren(QtWidgets.QWidget)
               if w.isVisible() and w.objectName()==name]
        if len(found)!=1:
            raise RuntimeError('Expected exactly one visible widget: '+name)
        return found[0]

    def menu_inventory(self):
        inventory={}
        def walk(menu,path):
            rows=[]
            for item in menu.items():
                row={'path':path+[item.name()],'submenu':isinstance(item,nuke.Menu)}
                for field,method in [('shortcut','shortcut'),('enabled','enabled')]:
                    if hasattr(item,method):
                        try: row[field]=getattr(item,method)()
                        except Exception: pass
                rows.append(row)
                if isinstance(item,nuke.Menu): rows.extend(walk(item,row['path']))
            return rows
        for name in ['Nuke','Nodes','Pane','Viewer','Animation','Node Graph']:
            menu=nuke.menu(name)
            inventory[name]=walk(menu,[name]) if menu else {'unavailable':True}
        dump(self.root/'menu-inventory.json',inventory)
        self.result['menu_inventory_counts']={k:len(v) for k,v in inventory.items() if isinstance(v,list)}

    def start(self):
        self.menu_inventory()
        self.snapshot('Compositing workspace','Workspace')
        for name in ['Viewer.1','DAG.1','Properties.1','Toolbar.1']:
            self.snapshot(name,'Panels',self.target(name))
        self.jobs.append(('Verify viewer change',self.change_viewer,self.verify_viewer))
        self.jobs.append(('Restore viewer',lambda:nuke.toNode('Reference_Grade')['multiply'].setValue(0.7),lambda:None))
        self.jobs.append(('Verify node movement',self.change_graph,self.verify_graph))
        self.jobs.append(('Restore graph',lambda:nuke.toNode('Reference_Grade').setXYpos(0,100),lambda:None))
        bars=[b for b in self.window.findChildren(QtWidgets.QTabBar) if b.isVisible()]
        dump(self.root/'tab-inventory.json',[
            {'bar':i,'tabs':[b.tabText(j) for j in range(b.count())],'selected':b.currentIndex()}
            for i,b in enumerate(bars)])
        for bi,bar in enumerate(bars):
            original=bar.currentIndex()
            for i in range(bar.count()):
                text=bar.tabText(i)
                self.jobs.append((f'Tab {bi}: {text}',lambda b=bar,j=i:b.setCurrentIndex(j),
                    lambda t=text:self.snapshot(t,'Workspace tabs')))
            self.jobs.append(('Restore tab',lambda b=bar,j=original:b.setCurrentIndex(j),lambda:None))
        menu_titles=set()
        for action in self.window.menuBar().actions():
            menu=action.menu()
            if menu and action.isVisible() and action.text() not in menu_titles:
                title=action.text()
                menu_titles.add(title)
                self.jobs.append(('Menu '+title,lambda t=title:self.open_menu(t),
                                  lambda t=title:self.menu_snapshot(self.visible_menu(),t)))
        for kind in ['Read','Write','Constant','CheckerBoard2','Grade','ColorCorrect','Blur','Merge2',
                     'Transform','Shuffle2','Keyer','Roto','Tracker4','CameraTracker']:
            self.jobs.append(('Node '+kind,lambda k=kind:self.show_node(k),
                              lambda k=kind:self.snapshot(k,'Node properties',self.target('Properties.1'))))
        for name in ['Large Node Graph','Large Viewer','Scripting','Animation','3D','Compositing']:
            self.jobs.append(('Workspace '+name,lambda n=name:self.switch_workspace(n),
                              lambda n=name:self.snapshot(n,'Workspaces')))
        self.next()

    def find_menu(self,title):
        matches=[a.menu() for a in self.window.menuBar().actions() if a.text()==title and a.menu() and a.isVisible()]
        if len(matches)!=1:
            raise RuntimeError('Expected one current menu: '+title)
        return matches[0]

    def open_menu(self,title):
        # Nuke rebuilds and deletes some QMenus during aboutToShow. Let the
        # menubar dispatch its normal event, then reacquire the visible popup.
        bar=self.window.menuBar()
        actions=[a for a in bar.actions() if a.text()==title and a.isVisible()]
        if len(actions)!=1:
            raise RuntimeError('Expected one visible menu action: '+title)
        point=QtCore.QPointF(bar.actionGeometry(actions[0]).center())
        global_point=QtCore.QPointF(bar.mapToGlobal(point.toPoint()))
        for event_type,buttons in [(QtCore.QEvent.MouseButtonPress,QtCore.Qt.LeftButton),
                                   (QtCore.QEvent.MouseButtonRelease,QtCore.Qt.NoButton)]:
            event=QtGui.QMouseEvent(event_type,point,global_point,QtCore.Qt.LeftButton,buttons,QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(bar,event)

    def visible_menu(self):
        menus=[w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w,QtWidgets.QMenu) and w.isVisible()]
        if len(menus)!=1:
            raise RuntimeError('Expected one visible popup menu; found '+str(len(menus)))
        return menus[0]

    def switch_workspace(self,name):
        menu=self.find_menu('Workspace')
        matches=[a for a in menu.actions() if a.text()==name]
        if len(matches)!=1:
            raise RuntimeError('Expected one workspace action: '+name)
        matches[0].trigger()

    def change_viewer(self):
        _,surfaces=capture_window(self.window)
        self.viewer_before=next(s for s in surfaces if any(o['class']=='Image_Window' for o in s['owners']))
        nuke.toNode('Reference_Grade')['multiply'].setValue(0.15)

    def verify_viewer(self):
        surfaces=self.snapshot('Viewer after Grade change','Verification',self.target('Viewer.1'))
        after=next(s for s in surfaces if any(o['class']=='Image_Window' for o in s['owners']))
        self.verification['viewer']={'before':self.viewer_before,'after':after,
                                    'changed':self.viewer_before['sha256']!=after['sha256']}
        if not self.verification['viewer']['changed']:
            raise RuntimeError('Viewer did not change after changing Grade')

    def show_node(self,kind):
        if self.current_node:
            self.current_node.hideControlPanel()
        self.current_node=getattr(nuke.nodes,kind)(name='Atlas_'+kind)
        self.current_node.setXYpos(500,len(self.entries)*80)
        nuke.show(self.current_node)
        values=[]
        for name,knob in self.current_node.knobs().items():
            row={'name':name,'label':knob.label(),'class':knob.Class(),'tooltip':knob.tooltip()}
            try: row['script']=knob.toScript()
            except Exception as e: row['script_error']=str(e)
            values.append(row)
        dump(self.directory/('knobs-'+kind+'.json'),values)

    def change_graph(self):
        _,surfaces=capture_window(self.window)
        self.graph_before=next(s for s in surfaces if any(o['class']=='DAG_Window' for o in s['owners']))
        nuke.toNode('Reference_Grade').setXYpos(180,100)

    def verify_graph(self):
        surfaces=self.snapshot('Node graph after moving Grade','Verification',self.target('DAG.1'))
        after=next(s for s in surfaces if any(o['class']=='DAG_Window' for o in s['owners']))
        self.verification['node_graph']={'before':self.graph_before,'after':after,
                                       'changed':self.graph_before['sha256']!=after['sha256']}
        if not self.verification['node_graph']['changed']:
            raise RuntimeError('Node graph did not change after moving Grade')

    def menu_snapshot(self,menu,title):
        try:
            filename=f'{len(self.entries):03d}-menu-{slug(title)}.png'
            if not menu.grab().save(str(self.directory/filename)):
                raise RuntimeError('Menu capture failed')
            actions=[{'text':a.text(),'enabled':a.isEnabled(),'checked':a.isChecked(),
                      'shortcut':a.shortcut().toString(),'submenu':a.menu() is not None} for a in menu.actions()]
            dump(self.directory/(Path(filename).stem+'.json'),actions)
            self.qtmenus[title]=actions
            self.entries.append({'title':title,'category':'Menus','image':filename,
                                 'evidence':Path(filename).stem+'.json'})
        finally:
            menu.hide()

    def next(self):
        if not self.jobs:
            self.finish()
            return
        title,action,capture=self.jobs.pop(0)
        dump(self.root/'progress.json',{'current':title,'remaining':len(self.jobs),'captured':len(self.entries)})
        try:
            action()
        except Exception:
            self.failures.append({'case':title,'error':traceback.format_exc()})
            QtCore.QTimer.singleShot(10,self.next)
            return
        def after():
            try: capture()
            except Exception: self.failures.append({'case':title,'error':traceback.format_exc()})
            QtCore.QTimer.singleShot(50,self.next)
        QtCore.QTimer.singleShot(1500,after)

    def finish(self):
        dump(self.root/'verification.json',self.verification)
        dump(self.root/'qt-menu-inventory.json',self.qtmenus)
        dump(self.root/'atlas-manifest.json',{'entries':self.entries,'failures':self.failures})
        cards=[]
        for e in self.entries:
            cards.append('<article><h2>'+html.escape(e['title'])+'</h2><p>'+html.escape(e['category'])+
                         '</p><a href="atlas/'+e['image']+'"><img loading="lazy" src="atlas/'+e['image']+
                         '"></a><p><a href="atlas/'+e['evidence']+'">Inspection data</a></p></article>')
        page='''<!doctype html><html><meta charset="utf-8"><title>NukeX UI atlas</title>
<style>body{background:#17191c;color:#ddd;font:16px system-ui;margin:30px}h1{font-size:30px}
input{padding:12px;width:50%;background:#272b30;color:white;border:1px solid #666}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:24px}article{background:#24282d;padding:18px}img{max-width:100%;max-height:500px;object-fit:contain}a{color:#9bc8ff}</style>
<h1>NukeX UI atlas</h1><p>Observed reference states from the installed application. Safe mode excludes third-party plug-ins.
Node panels show their initial visible region. This is a structural inventory and representative capture set, not complete behavioral coverage.</p>
<p><a href="menu-inventory.json">Menu inventory</a> · <a href="tab-inventory.json">Tab inventory</a> · <a href="verification.json">GPU verification</a> · <a href="atlas-manifest.json">Coverage and failures</a></p>
<input placeholder="Filter panels, nodes, menus" oninput="document.querySelectorAll('article').forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(this.value.toLowerCase()))"><main>'''+''.join(cards)+'</main></html>'
        (self.root/'index.html').write_text(page,encoding='utf-8')
        self.result.update({'ok':not self.failures,'atlas_captures':len(self.entries),'failures':self.failures,
                            'viewer_change_verified':self.verification.get('viewer',{}).get('changed',False),
                            'graph_change_verified':self.verification.get('node_graph',{}).get('changed',False)})
        self.publish(self.result)

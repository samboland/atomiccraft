"""Sequential UI state capture inside an isolated, disposable Nuke process.

Only allowlisted commands execute. Menu discovery never executes leaf actions.
Local Qt events do not inject desktop input or move the desktop cursor.
"""
import hashlib
import json
import traceback
from pathlib import Path
import nuke
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import getCppPointer, isValid
from ui_atlas import Atlas, controls, dump, slug
from gpu_capture import capture_window


class Explorer(Atlas):
    def __init__(self,window,root,publish,result,request):
        super().__init__(window,root,publish,result)
        self.request=request
        self.section=request['explore']
        self.observations=[]
        self.seen_menus=set()
        self.menu_signatures={}
        self.current_node=None

    def checkpoint(self):
        temporary=self.root/'atlas-manifest.tmp'
        dump(temporary,{'section':self.section,'entries':self.entries,
             'failures':self.failures,'observations':self.observations})
        temporary.replace(self.root/'atlas-manifest.json')

    def save_widget(self,title,widget,gpu=False):
        if not widget.isVisible():
            raise RuntimeError('Target is no longer visible: '+title)
        pixels,surfaces=capture_window(widget) if gpu else (widget.grab().toImage(),[])
        name=f'{len(self.entries):05d}-{slug(title)[:160]}'
        path=self.directory/(name+'.png')
        if pixels.isNull() or not pixels.save(str(path)):
            raise RuntimeError('Empty or unsaved capture: '+title)
        data={'title':title,'category':self.section,'image':path.name,
              'size':[pixels.width(),pixels.height()],'device_pixel_ratio':pixels.devicePixelRatio(),
              'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'gpu':surfaces,'controls':controls(widget),'widget_class':widget.metaObject().className(),
              'widget_name':widget.objectName(),'window_title':widget.windowTitle()}
        if isinstance(widget,QtWidgets.QMenu):
            data['actions']=[{'text':a.text(),'enabled':a.isEnabled(),'checkable':a.isCheckable(),
                'checked':a.isChecked(),'shortcut':a.shortcut().toString(),'submenu':bool(a.menu())}
                for a in widget.actions()]
        dump(self.directory/(name+'.json'),data)
        self.entries.append({k:data[k] for k in ['title','category','image','size','sha256']}
                            | {'evidence':name+'.json'})
        self.checkpoint()

    def scene(self,title):
        self.save_widget(title,self.window,True)
        extras=[w for w in QtWidgets.QApplication.topLevelWidgets()
                if isValid(w) and w.isVisible() and w is not self.window and w.width()>30 and w.height()>30
                and w.metaObject().className()!='Foundry::UI::Chart']
        for i,w in enumerate(extras):
            self.save_widget(title+' floating '+str(i)+' '+w.windowTitle(),w,
                             not isinstance(w,(QtWidgets.QMenu,QtWidgets.QDialog)))

    def add(self,title,action=lambda:None,capture=None):
        self.jobs.append((title,action,capture or (lambda t=title:self.scene(t))))

    def prepend(self,jobs):
        self.jobs[0:0]=jobs

    def close_popups(self):
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isValid(w) and w.isVisible() and (isinstance(w,QtWidgets.QMenu) or w.metaObject().className()=='DAGNodeChooser'): w.hide()
        popup=QtWidgets.QApplication.activePopupWidget()
        if popup: popup.hide()

    def start(self):
        self.menu_inventory()
        getattr(self,'plan_'+self.section)()
        self.next()

    def next(self):
        if not self.jobs:
            self.finish()
            return
        title,action,capture=self.jobs.pop(0)
        dump(self.root/'progress.json',{'current':title,'remaining':len(self.jobs),'captured':len(self.entries)})
        # Arm the capture before an action: modal dialogs run nested Qt loops.
        state={'failed':False}
        def after():
            if not state['failed']:
                try: capture()
                except Exception: self.failures.append({'case':title,'error':traceback.format_exc()})
            self.checkpoint()
            QtCore.QTimer.singleShot(20,self.next)
        delay=800 if title.startswith('Properties ') else (450 if self.section!='properties' else 100)
        if self.section=='properties' and title.startswith(('Restore ','Close ')): delay=30
        if title=='Second viewer settled': delay=2500
        QtCore.QTimer.singleShot(delay,after)
        try: action()
        except Exception:
            state['failed']=True
            self.failures.append({'case':title,'error':traceback.format_exc()})

    def finish(self):
        # Publish completion only after the richer manifest is durable.
        publish=self.publish
        def complete(result):
            self.checkpoint()
            result.pop('viewer_change_verified',None)
            result.pop('graph_change_verified',None)
            publish(result)
        self.publish=complete
        super().finish()

    def plan_layouts(self):
        menu=self.find_menu('Workspace')
        excluded={'Save Workspace...','Delete Workspace...','Reset Workspace','Edit Workspace Details'}
        names=[]
        for a in menu.actions():
            text=a.text()
            if text=='Previous Pane': break
            if text and text not in excluded and not text.startswith('Save '): names.append(text)
        dump(self.root/'workspace-inventory.json',names)
        for name in names:
            self.add('Workspace '+name,lambda n=name:self.switch_workspace(n),
                     lambda n=name:(self.scene('Workspace '+n),self.queue_tabs(n)))
        self.add('Restore Compositing',lambda:self.switch_workspace('Compositing'))
        for size in [(1000,700),(1920,1080),(1600,1000)]:
            self.add('Window '+str(size),lambda s=size:self.window.resize(*s))

    def queue_tabs(self,prefix,scope=None,details=False):
        scope=scope or self.window
        jobs=[]
        for bi,bar in enumerate(scope.findChildren(QtWidgets.QTabBar)):
            if not bar.isVisible(): continue
            if details:
                identity=(getCppPointer(bar)[0],tuple(bar.tabText(j) for j in range(bar.count())))
                if identity in self.property_tabs_seen: continue
                self.property_tabs_seen.add(identity)
            original=bar.currentIndex()
            for i in range(bar.count()):
                title=prefix+' / '+str(bi)+' '+bar.tabText(i)
                jobs.append((title,lambda b=bar,j=i:b.setCurrentIndex(j),
                    lambda t=title,s=scope,d=details:self.capture_tab(t,s,d)))
            jobs.append(('Restore tab '+prefix,lambda b=bar,j=original:b.setCurrentIndex(j),lambda:None))
        self.prepend(jobs)

    def capture_tab(self,title,scope,details):
        if scope is self.window: self.scene(title)
        else: self.save_widget(title,scope)
        if details:
            self.queue_controls(title,scope)
            self.queue_tabs(title,scope,True)

    def plan_menus(self):
        for a in self.window.menuBar().actions():
            if a.menu() and a.isVisible():
                self.add('Menu '+a.text(),lambda t=a.text():(self.close_popups(),self.open_menu(t)),
                         lambda t=a.text():self.menu_tree(t,self.active_menu()))
        for b in self.window.findChildren(QtWidgets.QToolButton):
            if b.isVisible() and b.metaObject().className()=='NukeToolButton':
                path='Nodes/'+b.text()
                self.add(path,lambda t=b.text():self.open_toolbar_menu(t),lambda p=path:self.menu_tree(p,self.active_menu()))

    def menu_tree(self,path,menu):
        if len(path.split('/'))>8: raise RuntimeError('Menu depth exceeded: '+path)
        signature=tuple(a.text() for a in menu.actions())
        if any(path.startswith(parent+'/') and signature==value for parent,value in self.menu_signatures.items()):
            raise RuntimeError('Submenu still has parent contents: '+path)
        self.menu_signatures[path]=signature
        self.save_widget(path,menu)
        items=[{'text':a.text(),'submenu':bool(a.menu()),'enabled':a.isEnabled(),
                'shortcut':a.shortcut().toString()} for a in menu.actions()]
        self.observations.append({'menu':path,'actions':items})
        jobs=[]
        for action in menu.actions():
            child=action.menu()
            key=path+'/'+action.text()
            if child and key not in self.seen_menus:
                self.seen_menus.add(key)
                jobs.append((key,lambda m=menu,t=action.text():self.open_child_menu(m,t),
                             lambda p=key:self.menu_tree(p,self.active_menu())))
        jobs.append(('Close '+path,lambda m=menu:m.hide() if isValid(m) else None,lambda:None))
        self.prepend(jobs)

    def open_child_menu(self,menu,text):
        if not isValid(menu): raise RuntimeError('Parent menu was deleted')
        matches=[a for a in menu.actions() if a.text()==text]
        if len(matches)!=1: raise RuntimeError('Missing submenu '+text)
        position=menu.mapToGlobal(menu.actionGeometry(matches[0]).topRight())
        child=matches[0].menu()
        if not child: raise RuntimeError('Action has no submenu '+text)
        child.popup(position)

    def active_menu(self):
        menu=QtWidgets.QApplication.activePopupWidget()
        if not isinstance(menu,QtWidgets.QMenu): raise RuntimeError('No active submenu')
        return menu

    def open_toolbar_menu(self,title):
        self.close_popups()
        found=[b for b in self.window.findChildren(QtWidgets.QToolButton)
               if b.isVisible() and b.metaObject().className()=='NukeToolButton' and b.text()==title]
        if len(found)!=1: raise RuntimeError('Missing toolbar category '+title)
        # click() enters a nested Qt loop. Queued jobs open child menus there.
        found[0].click()

    def graph_widget(self):
        found=[w for w in self.window.findChildren(QtWidgets.QWidget)
               if isValid(w) and w.isVisible() and w.metaObject().className()=='DAG_Window']
        if len(found)!=1: raise RuntimeError('Expected one DAG_Window')
        return found[0]

    def key(self,widget,key,text='',mod=QtCore.Qt.NoModifier):
        widget.setFocus()
        for kind in [QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease]:
            QtWidgets.QApplication.sendEvent(widget,QtGui.QKeyEvent(kind,key,mod,text))

    def context(self,widget):
        p=widget.rect().center()
        for kind,buttons in [(QtCore.QEvent.MouseButtonPress,QtCore.Qt.RightButton),(QtCore.QEvent.MouseButtonRelease,QtCore.Qt.NoButton)]:
            QtWidgets.QApplication.sendEvent(widget,QtGui.QMouseEvent(kind,QtCore.QPointF(p),QtCore.QPointF(widget.mapToGlobal(p)),QtCore.Qt.RightButton,buttons,QtCore.Qt.NoModifier))
        QtWidgets.QApplication.sendEvent(widget,QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse,p,widget.mapToGlobal(p)))

    def plan_graph(self):
        self.add('Connected graph')
        self.add('Multiple selected nodes',lambda:[n['selected'].setValue(True) for n in nuke.allNodes()])
        self.add('Graph context menu',lambda:self.context(self.graph_widget()))
        self.add('Close context menu',self.close_popups,lambda:None)
        self.add('Node search',lambda:self.key(self.graph_widget(),QtCore.Qt.Key_Tab))
        self.add('Node search Blur',self.search_blur)
        self.add('Close node search',lambda:(self.key(self.graph_widget(),QtCore.Qt.Key_Escape),self.close_popups()),lambda:None)
        self.add('Disconnected Grade',lambda:nuke.toNode('Reference_Grade').setInput(0,None))
        self.add('Reconnected Grade',lambda:nuke.toNode('Reference_Grade').setInput(0,nuke.toNode('Reference_Checker')))
        self.add('Disabled Grade',lambda:nuke.toNode('Reference_Grade')['disable'].setValue(True))
        self.add('Enabled Grade',lambda:nuke.toNode('Reference_Grade')['disable'].setValue(False))
        self.add('Marquee drag start',lambda:self.graph_mouse(QtCore.QEvent.MouseButtonPress,0.2,0.2,QtCore.Qt.LeftButton))
        self.add('Marquee dragging',lambda:self.graph_mouse(QtCore.QEvent.MouseMove,0.7,0.8,QtCore.Qt.LeftButton))
        self.add('Marquee drag release',lambda:self.graph_mouse(QtCore.QEvent.MouseButtonRelease,0.7,0.8,QtCore.Qt.NoButton))
        def extras():
            nuke.nodes.BackdropNode(name='Reference_Backdrop',label='Reference composite',xpos=-100,ypos=-80,bdwidth=400,bdheight=400)
            nuke.nodes.Dot(name='Reference_Dot',inputs=[nuke.toNode('Reference_Grade')],xpos=180,ypos=100)
            group=nuke.nodes.Group(name='Reference_Group',xpos=350,ypos=100)
            with group:
                source=nuke.nodes.Input(xpos=0,ypos=0)
                blur=nuke.nodes.Blur(inputs=[source],xpos=0,ypos=90)
                nuke.nodes.Output(inputs=[blur],xpos=0,ypos=180)
            nuke.zoom(0.7,[150,100])
        self.add('Backdrop dot and group',extras)
        self.add('Group properties',lambda:nuke.toNode('Reference_Group').showControlPanel())
        self.add('Inside group',lambda:nuke.showDag(nuke.toNode('Reference_Group')))
        self.add('Graph zoom out',lambda:nuke.zoom(0.3,[100,100]))
        self.add('Graph zoom in',lambda:nuke.zoom(1.5,[100,100]))

    def graph_mouse(self,kind,x,y,buttons):
        w=self.graph_widget(); p=QtCore.QPointF(w.width()*x,w.height()*y)
        button=QtCore.Qt.NoButton if kind==QtCore.QEvent.MouseMove else QtCore.Qt.LeftButton
        QtWidgets.QApplication.sendEvent(w,QtGui.QMouseEvent(kind,p,QtCore.QPointF(w.mapToGlobal(p.toPoint())),button,buttons,QtCore.Qt.NoModifier))

    def search_blur(self):
        found=[w for w in QtWidgets.QApplication.topLevelWidgets() if isValid(w) and w.isVisible() and w.metaObject().className()=='DAGNodeChooser']
        if len(found)!=1: raise RuntimeError('Node chooser did not appear')
        edits=found[0].findChildren(QtWidgets.QLineEdit)
        if len(edits)!=1: raise RuntimeError('Expected one node search field')
        edits[0].setText('Blur')
        edits[0].textEdited.emit('Blur')

    def plan_viewer(self):
        viewer=nuke.activeViewer().node()
        self.viewer=viewer
        dump(self.root/'viewer-knobs.json',[{'name':k,'class':v.Class(),'script':v.toScript()} for k,v in viewer.knobs().items()])
        viewer.setInput(1,nuke.toNode('Reference_Checker'))
        self.add('Viewer controls',capture=lambda:(self.scene('Viewer controls'),self.queue_controls('Viewer',self.target('Viewer.1'))))
        for tip in ['Toggle compare mode','Enables Region-Of-Interest','Set the current zoom level']:
            self.add('Viewer '+tip,lambda t=tip:self.viewer_button(t),lambda t=tip:self.scene(t))
            self.add('Close viewer popup',self.close_popups,lambda:None)
            if tip!='Set the current zoom level':
                self.add('Restore '+tip,lambda t=tip:self.viewer_button(t),lambda:None)
        for key,values in [('channels',['rgba','rgb','alpha','rgba']),('viewerProcess',['None','sRGB']),
                           ('show_overscan',[True,False]),('format_center',[True,False]),('gain',[2,1]),('gamma',[0.5,1])]:
            for value in values:
                self.add('Viewer '+key+' '+str(value),lambda k=key,v=value:viewer[k].setValue(v))
        self.add('Viewer B side',lambda:nuke.activeViewer().activateInput(1,1))
        self.add('Viewer A side',lambda:nuke.activeViewer().activateInput(0,0))
        for frame in [1,25,50]: self.add('Timeline frame '+str(frame),lambda f=frame:nuke.frame(f))
        self.add('Second viewer',lambda:nuke.show(nuke.nodes.Viewer(inputs=[nuke.toNode('Reference_Checker')])))
        self.add('Second viewer settled',lambda:nuke.activeViewer().activateInput(0,0))

    def viewer_button(self,tooltip):
        buttons=[w for w in self.target('Viewer.1').findChildren(QtWidgets.QAbstractButton)
                 if isValid(w) and w.isVisible() and w.toolTip().startswith(tooltip)]
        if len(buttons)!=1: raise RuntimeError('Expected viewer button: '+tooltip)
        buttons[0].click()

    def plan_panels(self):
        def populated():
            grade=nuke.toNode('Reference_Grade')
            knob=grade['multiply']; knob.setAnimated(); knob.setValueAt(0.3,1); knob.setValueAt(1.5,50); knob.setValueAt(0.7,100)
            transform=nuke.nodes.Transform(name='Animated_Transform',inputs=[grade])
            transform['translate'].setAnimated(0)
            transform['translate'].setValueAt(0,1,0); transform['translate'].setValueAt(200,100,0)
            transform.showControlPanel()
        self.add('Animated controls',populated)
        self.add('Animation workspace populated',lambda:self.switch_workspace('Animation'),
                 lambda:(self.scene('Animation workspace populated'),self.queue_tabs('Animation')))
        self.add('Compositing restore',lambda:self.switch_workspace('Compositing'))
        def roto():
            import nuke.rotopaint as rp
            node=nuke.nodes.Roto(name='Reference_Roto',inputs=[nuke.toNode('Reference_Checker')])
            curves=node['curves']; shape=rp.Shape(curves); shape.name='Reference shape'
            for x,y in [(200,200),(700,200),(700,600),(200,600)]:
                p=rp.ShapeControlPoint(); p.center.setPosition((x,y)); shape.append(p)
            curves.rootLayer.append(shape); curves.changed()
            nuke.activeViewer().node().setInput(0,node); node.showControlPanel()
        self.add('Roto shape and controls',roto)
        def track():
            node=nuke.nodes.Tracker4(name='Reference_Tracker',inputs=[nuke.toNode('Reference_Checker')])
            node['add_track'].execute(); node.showControlPanel()
            nuke.activeViewer().node().setInput(0,node)
        self.add('Tracker with a track',track)
        self.add('Tracker add track button',lambda:self.click_text('add track'))
        def scene3d():
            sphere=nuke.nodes.Sphere(name='Reference_Sphere')
            camera=nuke.nodes.Camera2(name='Reference_Camera')
            camera['translate'].setValue(8,2)
            scene=nuke.nodes.Scene(inputs=[sphere,camera])
            nuke.activeViewer().node().setInput(0,scene)
            self.switch_workspace('3D')
        self.add('Populated 3D workspace',scene3d,
                 lambda:(self.scene('Populated 3D workspace'),self.queue_tabs('3D')))
        def modern_scene():
            sphere=nuke.nodes.GeoSphere(name='Reference_GeoSphere')
            scene=nuke.nodes.GeoScene(inputs=[sphere])
            nuke.activeViewer().node().setInput(0,scene)
            self.switch_workspace('3D')
        self.add('New 3D Scene Graph',modern_scene)

    def click_text(self,text):
        matches=[b for b in self.window.findChildren(QtWidgets.QAbstractButton) if b.isVisible() and b.text()==text]
        if len(matches)!=1: raise RuntimeError('Expected one button '+text)
        matches[0].click()

    def trigger(self,path):
        item=nuke.menu('Nuke').findItem(path)
        if item:
            item.invoke()
            return
        parent,label=path.split('/',1)
        self.open_menu(parent)
        menu=self.active_menu()
        matches=[a for a in menu.actions() if a.text()==label and a.isEnabled()]
        if len(matches)!=1: raise RuntimeError('Menu command unavailable: '+path)
        matches[0].trigger()

    def capture_dialog(self,title):
        windows=[w for w in QtWidgets.QApplication.topLevelWidgets()
                 if isValid(w) and w.isVisible() and isinstance(w,QtWidgets.QDialog)]
        self.scene(title)
        if not windows:
            self.observations.append({'case':title,'note':'No QDialog; captured the observed main-window state'})
            self.queue_tabs(title,self.window,False)
        else:
            jobs=[]
            for w in windows:
                if 'Preferences' in title:
                    for tree in w.findChildren(QtWidgets.QTreeWidget):
                        iterator=QtWidgets.QTreeWidgetItemIterator(tree)
                        while iterator.value():
                            item=iterator.value(); t=title+' / '+item.text(0)
                            jobs.append((t,lambda tree=tree,item=item:tree.setCurrentItem(item),lambda t=t,w=w:self.save_widget(t,w)))
                            iterator+=1
                    for tree in w.findChildren(QtWidgets.QTreeView):
                        if isinstance(tree,QtWidgets.QTreeWidget): continue
                        model=tree.model()
                        def walk(parent=QtCore.QModelIndex(),prefix=''):
                            for row in range(model.rowCount(parent)):
                                index=model.index(row,0,parent)
                                label=str(model.data(index,QtCore.Qt.DisplayRole))
                                path=prefix+'/'+label if prefix else label
                                persistent=QtCore.QPersistentModelIndex(index)
                                t=title+' / '+path
                                jobs.append((t,lambda tree=tree,index=persistent:self.select_tree_page(tree,index),lambda t=t,w=w:self.save_widget(t,w)))
                                walk(index,path)
                        walk()
                for bi,b in enumerate(w.findChildren(QtWidgets.QTabBar)):
                    if b.isVisible():
                        for i in range(b.count()):
                            t=title+' tab '+str(bi)+' '+b.tabText(i)
                            jobs.append((t,lambda b=b,i=i:b.setCurrentIndex(i),lambda t=t,w=w:self.save_widget(t,w)))
                jobs.append(('Cancel '+title,w.reject,lambda:None))
            self.prepend(jobs)

    def select_tree_page(self,tree,index):
        index=QtCore.QModelIndex(index)
        tree.setCurrentIndex(index)
        tree.clicked.emit(index)

    def plan_dialogs(self):
        nuke.nodes.Write(name='Reference_Write',inputs=[nuke.toNode('Reference_Grade')])
        for path in ['File/Open Comp...','File/Save Comp As...','File/Insert Comp Nodes...',
                     'File/Export Comp Nodes...','Edit/Preferences...','Edit/Project Settings...',
                     'Viewer/Goto Frame...','Render/Render All Write Nodes...','Workspace/Save Workspace...']:
            self.add(path,lambda p=path:self.trigger(p),lambda p=path:self.capture_dialog(p))

    def queue_controls(self,prefix,scope):
        if prefix.endswith(' Node'):
            if getattr(self,'shared_node_controls',False):
                self.observations.append({'case':prefix,'note':'Shared Node tab controls already explored in this session; tab screenshot retained'})
                return
            self.shared_node_controls=True
        jobs=[]
        for i,button in enumerate(scope.findChildren(QtWidgets.QAbstractButton)):
            if button.metaObject().className()!='Foundry::UI::DisclosureButton' or not button.isVisible() or not button.isEnabled(): continue
            title=prefix+' expanded section '+str(i)
            jobs.append((title,button.click,lambda t=title,s=scope:self.save_widget(t,s)))
            jobs.append(('Restore '+title,button.click,lambda:None))
        for i,button in enumerate(scope.findChildren(QtWidgets.QAbstractButton)):
            if button.metaObject().className()!='Foundry::UI::ChoiceButton' or not button.isVisible() or not button.isEnabled(): continue
            title=prefix+' choice '+str(i)+' '+button.text()
            jobs.append((title,button.click,lambda t=title:self.capture_popups(t)))
            jobs.append(('Close '+title,self.close_popups,lambda:None))
        if self.current_node and self.current_node.Class() in ['Grade','Transform','Merge2','Read','Write','Roto','Tracker4']:
            seen=set()
            for button in scope.findChildren(QtWidgets.QAbstractButton):
                cls=button.metaObject().className()
                if cls not in ['Curve_Button','ExpressionButton','Picker_Button','MultipleButton']:
                    continue
                if not button.isVisible() or not button.isEnabled() or cls in seen: continue
                seen.add(cls)
                title=prefix+' '+cls
                jobs.append((title,button.click,lambda t=title,s=scope:self.capture_control_state(t,s)))
                restore=self.close_popups if cls in ['Curve_Button','ExpressionButton'] else button.click
                jobs.append(('Restore '+title,restore,lambda:None))
        for i,button in enumerate(scope.findChildren(QtWidgets.QToolButton)):
            if not button.isVisible() or not button.isEnabled() or not button.menu(): continue
            if button.metaObject().className()=='Foundry::UI::ChoiceButton': continue
            title=prefix+' menu '+str(i)+' '+button.text()
            jobs.append((title,button.showMenu,lambda t=title:self.capture_popups(t)))
            jobs.append(('Close '+title,self.close_popups,lambda:None))
        for i,box in enumerate(scope.findChildren(QtWidgets.QComboBox)):
            if not box.isVisible() or not box.isEnabled(): continue
            title=prefix+' dropdown '+str(i)+' '+box.currentText()
            jobs.append((title,box.showPopup,lambda t=title,b=box:self.capture_combo(t,b)))
            jobs.append(('Close '+title,lambda b=box:(b.hidePopup(),self.close_popups()),lambda:None))
        for i,bar in enumerate(scope.findChildren(QtWidgets.QScrollBar)):
            if not bar.isVisible() or bar.maximum()<=bar.minimum(): continue
            original=bar.value()
            # Page through every exposed scroll range; record values for review.
            step=max(1,bar.pageStep())
            values=list(range(bar.minimum(),bar.maximum(),step))+[bar.maximum()]
            for value in values:
                title=prefix+' scroll '+str(i)+' '+str(value)
                jobs.append((title,lambda b=bar,v=value:b.setValue(v),lambda t=title,s=scope:self.save_widget(t,s)))
            jobs.append(('Restore scroll',lambda b=bar,v=original:b.setValue(v),lambda:None))
        self.prepend(jobs)

    def capture_combo(self,title,box):
        popup=QtWidgets.QApplication.activePopupWidget()
        if popup and isValid(popup) and popup.isVisible():
            self.save_widget(title,popup)
        elif box.view().window().isVisible():
            self.save_widget(title,box.view().window())
        else:
            self.capture_popups(title)

    def capture_popups(self,title):
        menus=[w for w in QtWidgets.QApplication.topLevelWidgets() if isValid(w) and w.isVisible() and isinstance(w,QtWidgets.QMenu)]
        if not menus: raise RuntimeError('No visible popup for '+title)
        for i,w in enumerate(menus): self.save_widget(title+' '+str(i),w)

    def capture_control_state(self,title,scope):
        self.save_widget(title,scope)
        for i,w in enumerate(QtWidgets.QApplication.topLevelWidgets()):
            if isValid(w) and w.isVisible() and isinstance(w,(QtWidgets.QMenu,QtWidgets.QDialog)):
                self.save_widget(title+' popup '+str(i),w)

    def plan_properties(self):
        kinds=json.loads(Path(self.request['types']).read_text(encoding='utf-8')) if self.request.get('types') else [
            'Read','Write','Grade','ColorCorrect','Blur','Merge2','Transform','Shuffle2','Roto','Tracker4',
            'CameraTracker','Keyer','Camera2','ScanlineRender','ParticleEmitter','DeepMerge','Text2','VectorBlur']
        dump(self.root/'requested-types.json',kinds)
        for kind in kinds:
            self.add('Properties '+kind,lambda k=kind:self.node_properties(k),
                     lambda k=kind:self.property_details(k))

    def node_properties(self,kind):
        if self.current_node:
            self.current_node.hideControlPanel()
            nuke.delete(self.current_node)
        self.current_node=None
        self.current_node=getattr(nuke.nodes,kind)()
        self.panel_attempt=0
        self.property_tabs_seen=set()
        self.current_node.showControlPanel()

    def property_details(self,kind):
        dialogs=[w for w in QtWidgets.QApplication.topLevelWidgets() if isValid(w) and w.isVisible() and isinstance(w,QtWidgets.QDialog)]
        for i,w in enumerate(dialogs):
            self.save_widget(kind+' dialog '+str(i),w)
            w.reject()
        panel=self.target('Properties.1')
        if not any(w.get('text')==self.current_node.name() for w in controls(panel)):
            self.panel_attempt+=1
            if self.panel_attempt<=3:
                self.prepend([('Properties '+kind,self.current_node.showControlPanel,
                               lambda k=kind:self.property_details(k))])
                return
            self.scene(kind+' missing-panel observation')
            raise RuntimeError('Named property panel did not appear for '+kind)
        self.save_widget(kind+' initial',panel)
        self.queue_tabs(kind,panel,True)
        if kind in ['Grade','Transform','Merge2','Read','Write','Roto','Tracker4']:
            jobs=[]
            for key in ['black_clamp','white_clamp','invert_mask','enable_mix_luminance','invert_matrix','motionblur','use_limit']:
                knob=self.current_node.knob(key)
                if knob is None or knob.Class()!='Boolean_Knob': continue
                value=knob.value(); title=kind+' conditional '+key
                jobs.append((title,lambda k=knob,v=value:k.setValue(not v),lambda t=title,p=panel:self.save_widget(t,p)))
                jobs.append(('Restore '+title,lambda k=knob,v=value:k.setValue(v),lambda:None))
            self.prepend(jobs)
        # Initial controls also cover nodes whose panel has no Qt tab bar.
        if not any(b.isVisible() for b in panel.findChildren(QtWidgets.QTabBar)):
            self.queue_controls(kind+' initial',panel)

    def plan_interactions(self):
        for i,splitter in enumerate(self.window.findChildren(QtWidgets.QSplitter)):
            if not splitter.isVisible() or splitter.count()<2: continue
            original=splitter.sizes(); sizes=list(original)
            sizes[0]=max(1,int(sum(original)*0.7)); sizes[1]=max(1,sum(original)-sizes[0])
            self.add('Resized divider '+str(i),lambda s=splitter,v=sizes:s.setSizes(v))
            self.add('Restore divider '+str(i),lambda s=splitter,v=original:s.setSizes(v))
        bars=[b for b in self.window.findChildren(QtWidgets.QTabBar) if b.isVisible()]
        for i,bar in enumerate(bars):
            self.add('Pane context '+str(i),lambda b=bar:self.context(b))
            self.add('Close pane context',self.close_popups,lambda:None)
        self.add('Playback forwards',lambda:self.viewer_button('Play forwards/Stop.'))
        self.add('Playback stopped',lambda:self.viewer_button('Play forwards/Stop.'))
        self.add('Playback backwards',lambda:self.viewer_button('Play backwards/Stop.'))
        self.add('Playback stopped backwards',lambda:self.viewer_button('Play backwards/Stop.'))

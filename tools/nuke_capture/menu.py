"""Capture Nuke through its own Qt event loop on an isolated desktop."""
import json
import os
from pathlib import Path
import traceback
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gpu_capture import capture_window, crop_widget

if os.environ.get('ATOMIC_CAPTURE_ROOT'):
    import nuke
    from PySide6 import QtCore, QtWidgets

    root = Path(os.environ['ATOMIC_CAPTURE_ROOT'])
    request = json.loads((root / 'request.json').read_text())
    capture_attempts = 0
    (root / 'started.json').write_text(json.dumps({'version': nuke.NUKE_VERSION_STRING}))

    def publish(result):
        temp = root / 'result.tmp'
        temp.write_text(json.dumps(result,indent=2))
        temp.replace(root / 'result.json')

    def capture():
        global capture_attempts
        capture_attempts += 1
        try:
            app = QtWidgets.QApplication.instance()
            dialogs = [{'class':w.metaObject().className(),'title':w.windowTitle(),
                        'labels':[x.text() for x in w.findChildren(QtWidgets.QLabel)]}
                       for w in app.topLevelWidgets() if w.isVisible() and isinstance(w,QtWidgets.QDialog)]
            if dialogs:
                (root/'dialogs.json').write_text(json.dumps(dialogs,indent=2))
                raise RuntimeError('Visible dialog blocks reference capture; see dialogs.json. No dialog was accepted.')
            windows = [w for w in app.topLevelWidgets()
                       if w.isVisible() and isinstance(w, QtWidgets.QMainWindow)]
            if len(windows) != 1:
                raise RuntimeError('Expected one visible main window: ' + repr([(w.objectName(),w.windowTitle()) for w in windows]))
            window = windows[0]
            image, gpu = capture_window(window)
            if request.get('fixture'):
                classes = {owner['class']:surface for surface in gpu for owner in surface['owners']}
                for expected in ('Image_Window','DAG_Window'):
                    if expected not in classes or classes[expected]['sample_colors'] < 8:
                        if capture_attempts < 20:
                            QtCore.QTimer.singleShot(500,capture)
                            return
                        raise RuntimeError('Reference GPU surface is missing or blank: '+expected)
            (root/'gpu.json').write_text(json.dumps(gpu,indent=2))
            if image.isNull() or not image.save(str(root / 'main.png')):
                raise RuntimeError('Window capture failed')
            widgets = []
            for index, widget in enumerate(window.findChildren(QtWidgets.QWidget)):
                if not widget.isVisible():
                    continue
                origin = widget.mapTo(window, QtCore.QPoint(0, 0))
                widgets.append({'id':index, 'class':widget.metaObject().className(),
                    'name':widget.objectName(), 'title':widget.windowTitle(),
                    'rect':[origin.x(),origin.y(),widget.width(),widget.height()]})
            (root / 'widgets.json').write_text(json.dumps(widgets,indent=2))
            target = window
            if request.get('widget'):
                matches = [w for w in window.findChildren(QtWidgets.QWidget)
                           if w.isVisible() and w.objectName()==request['widget']]
                if len(matches)!=1:
                    raise ValueError('Widget selector must match exactly one visible widget')
                target = matches[0]
            if request.get('rect'):
                rect = QtCore.QRect(*request['rect'])
                if rect.isEmpty() or not target.rect().contains(rect):
                    raise ValueError('Capture rectangle is outside the target widget')
                selected = crop_widget(image,window,target,rect)
            else:
                selected = crop_widget(image,window,target)
            if selected.isNull() or not selected.save(str(root/'selected.png')):
                raise RuntimeError('Selected capture failed')
            menus = []
            def walk(menu, prefix):
                for item in menu.items():
                    path = prefix + [item.name()]
                    menus.append('/'.join(path))
                    if isinstance(item, nuke.Menu):
                        walk(item,path)
            walk(nuke.menu('Nuke'), ['Nuke'])
            (root / 'menus.json').write_text(json.dumps(menus,indent=2))
            result = {'ok':True,'version':nuke.NUKE_VERSION_STRING,
                'size':[image.width(),image.height()], 'device_pixel_ratio':image.devicePixelRatio(),
                'widgets':len(widgets), 'menus':len(menus)}
            if request.get('atlas'):
                from ui_atlas import Atlas
                global atlas
                atlas = Atlas(window,root,publish,result)
                atlas.start()
                return
        except Exception:
            result = {'ok':False,'error':traceback.format_exc()}
        publish(result)

    def prepare():
        try:
            windows = [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w,QtWidgets.QMainWindow) and w.isVisible()]
            if len(windows)!=1:
                raise RuntimeError('Expected one main window during preparation')
            windows[0].showNormal()
            windows[0].resize(*request.get('size',[1600,1000]))
            if request.get('catalog'):
                from node_catalog import NodeCatalog
                global catalog
                catalog = NodeCatalog(windows[0],Path(request['catalog']),publish,request.get('node_limit',60))
                catalog.start()
                return
            if request.get('fixture'):
                checker = nuke.nodes.CheckerBoard2(name='Reference_Checker')
                grade = nuke.nodes.Grade(name='Reference_Grade', inputs=[checker])
                grade['multiply'].setValue(0.7)
                viewer = nuke.nodes.Viewer(inputs=[grade])
                nuke.show(viewer)
                checker.setXYpos(0,0)
                grade.setXYpos(0,100)
                viewer.setXYpos(0,200)
                nuke.zoom(1,[0,100])
            if request.get('node'):
                node = nuke.createNode(request['node'], inpanel=True)
                nuke.show(node)
                knobs = [{'name':name,'class':knob.Class(),'label':knob.label()}
                         for name,knob in node.knobs().items()]
                (root/'knobs.json').write_text(json.dumps(knobs,indent=2))
        except Exception:
            publish({'ok':False,'error':traceback.format_exc()})
            return
        QtCore.QTimer.singleShot(5000,capture)

    QtCore.QTimer.singleShot(10000, prepare)

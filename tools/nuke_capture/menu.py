"""Capture Nuke through its own Qt event loop on an isolated desktop."""
import json
import os
from pathlib import Path
import traceback

if os.environ.get('ATOMIC_CAPTURE_ROOT'):
    import nuke
    from PySide6 import QtCore, QtWidgets

    root = Path(os.environ['ATOMIC_CAPTURE_ROOT'])
    request = json.loads((root / 'request.json').read_text())
    (root / 'started.json').write_text(json.dumps({'version': nuke.NUKE_VERSION_STRING}))

    def publish(result):
        temp = root / 'result.tmp'
        temp.write_text(json.dumps(result,indent=2))
        temp.replace(root / 'result.json')

    def capture():
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
            image = window.grab()
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
                selected = target.grab(rect)
            else:
                selected = target.grab()
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
        except Exception:
            result = {'ok':False,'error':traceback.format_exc()}
        publish(result)

    def prepare():
        try:
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

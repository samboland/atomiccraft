"""Capture Foundry's native GL child windows without desktop screenshots."""
import ctypes
from ctypes import wintypes
import hashlib
from PySide6 import QtCore, QtGui, QtWidgets


def read_surface(qwindow):
    """Read the presented front buffer using a private, temporary WGL context."""
    gl = ctypes.WinDLL('opengl32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetDC.argtypes = [ctypes.c_void_p]
    user.GetDC.restype = ctypes.c_void_p
    user.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user.GetClientRect.argtypes = [ctypes.c_void_p,ctypes.POINTER(wintypes.RECT)]
    gl.wglGetCurrentContext.restype = ctypes.c_void_p
    gl.wglGetCurrentDC.restype = ctypes.c_void_p
    gl.wglCreateContext.argtypes = [ctypes.c_void_p]
    gl.wglCreateContext.restype = ctypes.c_void_p
    gl.wglDeleteContext.argtypes = [ctypes.c_void_p]
    gl.wglMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gl.glReadPixels.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    hwnd = int(qwindow.winId())
    dc = user.GetDC(hwnd)
    previous_dc, previous_context = gl.wglGetCurrentDC(), gl.wglGetCurrentContext()
    context = None
    try:
        if not dc:
            raise RuntimeError('GetDC failed')
        context = gl.wglCreateContext(dc)
        if not context or not gl.wglMakeCurrent(dc, context):
            raise RuntimeError('Cannot bind capture context: ' + str(ctypes.get_last_error()))
        client = wintypes.RECT()
        if not user.GetClientRect(hwnd,ctypes.byref(client)):
            raise RuntimeError('Cannot measure GPU surface')
        width, height = client.right-client.left, client.bottom-client.top
        if not 0 < width * height <= 32000000:
            raise ValueError('Invalid or excessive GPU surface dimensions')
        gl.glReadBuffer(0x0404)  # GL_FRONT: the presented frame, never an unfinished back buffer.
        data = (ctypes.c_ubyte * (width * height * 4))()
        gl.glReadPixels(0, 0, width, height, 0x1908, 0x1401, data)
        error = gl.glGetError()
        if error:
            raise RuntimeError('OpenGL readback error: ' + hex(error))
        raw = bytes(data)
        image = QtGui.QImage(raw, width, height, QtGui.QImage.Format_RGBA8888).mirrored().copy()
        # Windows front buffers need not carry meaningful alpha.
        image = image.convertToFormat(QtGui.QImage.Format_RGB32)
        sample = image.scaled(160, 100)
        colors = {sample.pixel(x,y) for y in range(sample.height()) for x in range(sample.width())}
        return image, {'hwnd':hwnd, 'size':[width,height], 'sha256':hashlib.sha256(bytes(image.constBits())).hexdigest(),
                       'sample_colors':len(colors), 'source':'WGL GL_FRONT; temporary capture context'}
    finally:
        if context:
            gl.wglMakeCurrent(previous_dc, previous_context)
            gl.wglDeleteContext(context)
        if dc:
            user.ReleaseDC(hwnd,dc)


def capture_window(window):
    """Composite native GPU surfaces into the Qt snapshot at observed coordinates."""
    base = window.grab().toImage()
    records = []
    surfaces = []
    user = ctypes.WinDLL('user32')
    user.GetAncestor.argtypes = [ctypes.c_void_p,ctypes.c_uint]
    user.GetAncestor.restype = ctypes.c_void_p
    for native in QtGui.QGuiApplication.allWindows():
        if native.metaObject().className() != 'Foundry::UI::GLWindow' or not native.isVisible():
            continue
        if user.GetAncestor(int(native.winId()),2) != int(window.winId()):
            continue
        origin = window.mapFromGlobal(native.mapToGlobal(QtCore.QPoint(0,0)))
        rect = QtCore.QRect(origin, native.size())
        if not window.rect().contains(rect):
            continue
        pixels, evidence = read_surface(native)
        owners = [w for w in window.findChildren(QtWidgets.QWidget)
                  if w.isVisible() and w.size()==native.size()
                  and w.mapTo(window,QtCore.QPoint(0,0))==origin]
        evidence.update({'rect':[rect.x(),rect.y(),rect.width(),rect.height()],
                         'owners':[{'class':w.metaObject().className(),'name':w.objectName()} for w in owners]})
        surfaces.append((rect,pixels))
        records.append(evidence)
    painter = QtGui.QPainter(base)
    try:
        for rect,pixels in surfaces:
            painter.drawImage(QtCore.QRectF(rect), pixels)
    finally:
        painter.end()
    return base, records


def crop_widget(image, main, widget, rect=None):
    local = rect or widget.rect()
    if local.isEmpty() or not widget.rect().contains(local):
        raise ValueError('Capture rectangle is outside the target widget')
    origin = widget.mapTo(main, local.topLeft())
    ratio = image.devicePixelRatio()
    left, top = round(origin.x()*ratio), round(origin.y()*ratio)
    right = round((origin.x()+local.width())*ratio)
    bottom = round((origin.y()+local.height())*ratio)
    return image.copy(left,top,right-left,bottom-top)

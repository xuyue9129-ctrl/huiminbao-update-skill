"""Capture a specific window, without foreground activation or screen scraping."""
import ctypes as C
from ctypes import wintypes as W
import json
import struct
import sys
from PIL import Image
try: C.windll.shcore.SetProcessDpiAwareness(2)
except Exception: pass
u,g=C.WinDLL('user32',use_last_error=True),C.WinDLL('gdi32',use_last_error=True)
def sig(lib,n,args,r):
    f=getattr(lib,n); f.argtypes=args; f.restype=r; return f
sig(u,'GetWindowRect',[W.HWND,C.POINTER(W.RECT)],W.BOOL)
sig(u,'GetWindowDC',[W.HWND],W.HDC)
sig(u,'PrintWindow',[W.HWND,W.HDC,W.UINT],W.BOOL)
sig(u,'ReleaseDC',[W.HWND,W.HDC],C.c_int)
sig(g,'CreateCompatibleDC',[W.HDC],W.HDC)
sig(g,'CreateCompatibleBitmap',[W.HDC,C.c_int,C.c_int],W.HBITMAP)
sig(g,'SelectObject',[W.HDC,W.HANDLE],W.HANDLE)
sig(g,'DeleteObject',[W.HANDLE],W.BOOL)
sig(g,'DeleteDC',[W.HDC],W.BOOL)
sig(g,'GetDIBits',[W.HDC,W.HBITMAP,W.UINT,W.UINT,C.c_void_p,C.c_void_p,W.UINT],C.c_int)
h=int(sys.argv[1]); r=W.RECT()
if not u.GetWindowRect(h,C.byref(r)): raise RuntimeError('Invalid window')
w,hh=r.right-r.left,r.bottom-r.top
if w<=0 or hh<=0 or w*hh>40_000_000: raise RuntimeError('Invalid capture dimensions')
hdc=u.GetWindowDC(h); mdc=g.CreateCompatibleDC(hdc); bmp=g.CreateCompatibleBitmap(hdc,w,hh)
old=g.SelectObject(mdc,bmp)
try:
    if not u.PrintWindow(h,mdc,2): raise RuntimeError('Target did not provide a window image')
    g.SelectObject(mdc,old)
    bi=C.create_string_buffer(struct.pack('<IiiHHIIiiII',40,w,-hh,1,32,0,w*hh*4,0,0,0,0))
    buf=C.create_string_buffer(w*hh*4)
    if g.GetDIBits(mdc,bmp,0,hh,buf,bi,0)!=hh: raise RuntimeError('Incomplete window bitmap')
    im=Image.frombuffer('RGBA',(w,hh),buf,'raw','BGRA',0,1).convert('RGB')
    im.save(sys.argv[2])
    extrema=im.getextrema()
    print(json.dumps({'width':w,'height':hh,'uniform':all(lo==hi for lo,hi in extrema),'freshness':'must be visually verified'}))
finally:
    if old: g.SelectObject(mdc,old)
    if bmp: g.DeleteObject(bmp)
    if mdc: g.DeleteDC(mdc)
    if hdc: u.ReleaseDC(h,hdc)

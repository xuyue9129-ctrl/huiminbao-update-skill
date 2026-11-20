"""Window-targeted WeChat operations. Never inject global input or activate windows."""
import argparse
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
ALLOWED = {'weixin.exe', 'wechat.exe', 'wechatappex.exe', 'weixinappex.exe', 'wechatapp.exe'}
if os.name != 'nt':
    raise SystemExit('This tool requires Windows.')
u, k, g = C.WinDLL('user32', use_last_error=True), C.WinDLL('kernel32', use_last_error=True), C.WinDLL('gdi32', use_last_error=True)
def sig(lib, name, args, result):
    f = getattr(lib, name); f.argtypes = args; f.restype = result; return f
sig(u,'IsWindow',[W.HWND],W.BOOL)
sig(u,'IsIconic',[W.HWND],W.BOOL)
sig(u,'IsWindowVisible',[W.HWND],W.BOOL)
sig(u,'GetForegroundWindow',[],W.HWND)
sig(u,'GetWindowThreadProcessId',[W.HWND,C.POINTER(W.DWORD)],W.DWORD)
sig(u,'GetWindowTextW',[W.HWND,W.LPWSTR,C.c_int],C.c_int)
sig(u,'GetClassNameW',[W.HWND,W.LPWSTR,C.c_int],C.c_int)
sig(u,'GetWindowRect',[W.HWND,C.POINTER(W.RECT)],W.BOOL)
sig(u,'GetClientRect',[W.HWND,C.POINTER(W.RECT)],W.BOOL)
sig(u,'ClientToScreen',[W.HWND,C.POINTER(W.POINT)],W.BOOL)
sig(u,'GetCursorPos',[C.POINTER(W.POINT)],W.BOOL)
sig(u,'GetAncestor',[W.HWND,W.UINT],W.HWND)
sig(u,'IsChild',[W.HWND,W.HWND],W.BOOL)
sig(u,'PostMessageW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM],W.BOOL)
sig(k,'OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE)
sig(k,'QueryFullProcessImageNameW',[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)],W.BOOL)
sig(k,'CloseHandle',[W.HANDLE],W.BOOL)
sig(k,'CreateMutexW',[C.c_void_p,W.BOOL,W.LPCWSTR],W.HANDLE)
sig(k,'WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD)
sig(k,'ReleaseMutex',[W.HANDLE],W.BOOL)
CALLBACK = C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
sig(u,'EnumWindows',[CALLBACK,W.LPARAM],W.BOOL)
sig(u,'EnumChildWindows',[W.HWND,CALLBACK,W.LPARAM],W.BOOL)
try: C.windll.shcore.SetProcessDpiAwareness(2)
except Exception: pass

def title(h, cls=False):
    buf=C.create_unicode_buffer(2048)
    (u.GetClassNameW if cls else u.GetWindowTextW)(h,buf,len(buf))
    return buf.value

def process(h):
    pid=W.DWORD(); u.GetWindowThreadProcessId(h,C.byref(pid))
    handle=k.OpenProcess(0x1000,False,pid.value)
    if not handle: return pid.value,''
    try:
        buf=C.create_unicode_buffer(32768); size=W.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(handle,0,buf,C.byref(size)): return pid.value,''
        return pid.value,Path(buf.value).name
    finally: k.CloseHandle(handle)

def rect(h, client=False):
    r=W.RECT()
    if not (u.GetClientRect if client else u.GetWindowRect)(h,C.byref(r)): raise RuntimeError('Window rectangle unavailable')
    return [r.left,r.top,r.right,r.bottom]

def inspect(h):
    if not u.IsWindow(h): raise ValueError('Invalid/stale window handle; run windows again')
    pid,exe=process(h)
    if exe.lower() not in ALLOWED: raise ValueError('Target is not a supported WeChat process')
    origin=W.POINT(0,0); u.ClientToScreen(h,C.byref(origin))
    cursor=W.POINT(); u.GetCursorPos(C.byref(cursor))
    children=[]
    @CALLBACK
    def callback(child, unused):
        try: children.append({'hwnd':int(child),'class':title(child,True),'rect':rect(child)})
        except RuntimeError: pass
        return True
    u.EnumChildWindows(h,callback,0)
    return {'hwnd':h,'pid':pid,'process':exe,'title':title(h),'class':title(h,True),'visible':bool(u.IsWindowVisible(h)),
            'minimized':bool(u.IsIconic(h)),'foreground':u.GetAncestor(u.GetForegroundWindow(),2)==u.GetAncestor(h,2),
            'window_rect':rect(h),'client_rect':rect(h,True),'client_origin_screen':[origin.x,origin.y],
            'cursor':[cursor.x,cursor.y],'children':children}

def windows():
    result=[]
    @CALLBACK
    def callback(h, unused):
        if u.IsWindowVisible(h):
            try: result.append(inspect(int(h)))
            except (ValueError,RuntimeError): pass
        return True
    u.EnumWindows(callback,0)
    return result

def sanitize(text):
    blocked={'key','pass_ticket','exportkey','uin','wxtoken','ticket','access_token','authkey','poc_token','token'}
    def clean(match):
        value=match.group(0).replace('&amp;','&')
        try:
            p=urlsplit(value)
            host=p.hostname or ''
            if ':' in host: host='['+host+']'
            if p.port: host+=':'+str(p.port)
            return urlunsplit((p.scheme,host,p.path,urlencode([(a,b) for a,b in parse_qsl(p.query,keep_blank_values=True) if a.lower() not in blocked]),''))
        except ValueError: return '[unparseable source URL]'
    return re.sub(r'(?:https?|weixin)://[^\s<>\]"\)]+',clean,text)

def ps(script, *args):
    env=dict(os.environ)
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(ROOT/script),*map(str,args)],
                          capture_output=True,text=True,encoding='utf-8-sig',errors='replace',timeout=40,env=env,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError(sanitize((result.stderr or result.stdout).strip())[:1000])
    return sanitize(result.stdout.strip())

@contextmanager
def guard(h):
    handle=k.CreateMutexW(None,False,'Local\\WeChatBackgroundControl-'+str(h))
    if not handle: raise RuntimeError('Unable to acquire window lock')
    held=False
    try:
        code=k.WaitForSingleObject(handle,0)
        if code not in (0,0x80): raise RuntimeError('Another background operation holds this window')
        held=True
        state=inspect(h)
        if state['foreground']: raise RuntimeError('The target is in the foreground; no input was sent')
        if state['minimized']: raise RuntimeError('Target is minimized; no automatic restore or input performed')
        if state['process'].lower() not in {'wechatappex.exe','weixinappex.exe','wechatapp.exe'}:
            raise RuntimeError('Only independent research windows are supported, never the main chat window')
        yield state
        time.sleep(.15)
        if inspect(h)['foreground']: raise RuntimeError('Target activated itself; stop and observe. Do not repeat the action')
    finally:
        if held: k.ReleaseMutex(handle)
        k.CloseHandle(handle)

def post(h,msg,w=0,l=0):
    if not u.PostMessageW(h,msg,w,l): raise C.WinError(C.get_last_error())

def xy(x,y):
    if not(-32768<=x<=32767 and -32768<=y<=32767): raise ValueError('Coordinate outside window-message range')
    return ((y&0xffff)<<16)|(x&0xffff)

def char_units(text):
    raw=text.encode('utf-16-le')
    return [int.from_bytes(raw[i:i+2],'little') for i in range(0,len(raw),2)]

def capture(h,path):
    state=inspect(h)
    if state['minimized']: raise RuntimeError('Cannot verify a minimized window capture')
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'capture.py'),str(h),str(path)],capture_output=True,text=True,
                          encoding='utf-8',timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError(result.stderr.strip() or 'Window capture failed')
    return {'image':str(path.resolve()),'capture':json.loads(result.stdout),'window':state}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['windows','inspect','capture','read','find','invoke','setvalue','scrollinto','scroll','click','chars','key'])
    p.add_argument('--hwnd',type=int); p.add_argument('--target',type=int); p.add_argument('--out',type=Path)
    p.add_argument('--name',default='*'); p.add_argument('--type',default=''); p.add_argument('--exact',action='store_true')
    p.add_argument('--index',type=int); p.add_argument('--value',default='')
    p.add_argument('--x',type=int); p.add_argument('--y',type=int); p.add_argument('--frame',choices=['client','window'],default='client')
    p.add_argument('--by',type=float,default=0); p.add_argument('--set',type=float,default=-1)
    p.add_argument('--key',choices=['enter','esc','pgdn','pgup','end','home'])
    a=p.parse_args()
    if a.index is not None and a.index<0: p.error('--index cannot be negative')
    if a.command=='windows': return windows()
    if a.hwnd is None: p.error('--hwnd is required')
    state=inspect(a.hwnd)
    if a.command=='inspect': return state
    if state['process'].lower() not in {'wechatappex.exe','weixinappex.exe','wechatapp.exe'}:
        raise RuntimeError('Read/navigation is restricted to independent research windows')
    if a.command in ('capture','read') and not a.out: p.error('--out is required')
    if a.command=='capture': return capture(a.hwnd,a.out)
    if a.command=='read':
        with tempfile.TemporaryDirectory(prefix='wechat-background-read-') as temp:
            raw=Path(temp)/'raw.txt'; ps('doc.ps1','-Hwnd',a.hwnd,'-Out',raw)
            content=sanitize(raw.read_text(encoding='utf-8-sig'))
        a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(content,encoding='utf-8')
        return {'file':str(a.out.resolve()),'chars':len(content),'kind':'UIA document; verify publisher and page type'}
    params=['-Hwnd',a.hwnd,'-Name',a.name,'-Type',a.type]
    if a.exact: params+=['-Exact']
    if a.command=='find': return {'controls':ps('act.ps1',*params,'-Action','find')}
    with guard(a.hwnd) as state:
        if a.command in ('invoke','setvalue','scrollinto'):
            matches=ps('act.ps1',*params,'-Action','find')
            count=len([line for line in matches.splitlines() if re.match(r'^\d+ ',line)])
            if a.index is None and count!=1: raise RuntimeError('Expected one control, found %d; inspect matches and set --index'%count)
            result=ps('act.ps1',*params,'-Action',a.command,'-Index',a.index or 0,'-Value',a.value)
        elif a.command=='scroll':
            if a.set!=-1 and not 0<=a.set<=100: raise ValueError('--set must be 0..100')
            result=ps('sp.ps1','-Hwnd',a.hwnd,'-Set',a.set,'-By',a.by)
        else:
            target=a.target or a.hwnd
            if target!=a.hwnd and not u.IsChild(a.hwnd,target): raise ValueError('Target must be an observed child of selected window')
            if a.command=='click':
                if a.x is None or a.y is None: p.error('--x and --y required')
                x,y=a.x,a.y
                if a.frame=='window':
                    origin=W.POINT(0,0); u.ClientToScreen(target,C.byref(origin))
                    x+=state['window_rect'][0]-origin.x; y+=state['window_rect'][1]-origin.y
                bounds=rect(target,True)
                if not(bounds[0]<=x<bounds[2] and bounds[1]<=y<bounds[3]): raise ValueError('Click is outside target client area')
                post(target,0x200,0,xy(x,y)); post(target,0x201,1,xy(x,y)); time.sleep(.06); post(target,0x202,0,xy(x,y))
            elif a.command=='chars':
                if not a.value or len(a.value)>1000: raise ValueError('Expected 1..1000 characters')
                if any(x in a.value for x in ('\r','\n','\t')): raise ValueError('Use text only; submit with a separately verified key action')
                for unit in char_units(a.value): post(target,0x102,unit,1); time.sleep(.01)
            elif a.command=='key':
                if not a.key: p.error('--key required')
                vk={'enter':13,'esc':27,'pgdn':34,'pgup':33,'end':35,'home':36}[a.key]
                post(target,0x100,vk,1); post(target,0x101,vk,0xC0000001)
            result='posted to selected window only'
    return {'operation':a.command,'result':result,'next':'Re-read or capture the window to verify the effect'}

if __name__=='__main__':
    try: print(json.dumps({'ok':True,'data':main()},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False)); sys.exit(1)

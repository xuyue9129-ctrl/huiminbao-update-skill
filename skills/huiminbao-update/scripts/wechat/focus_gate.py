"""Temporary activation gate for WeChat processes during one background navigation.

A WH_CBT hook is installed only on threads of WeChat processes in the current session.
It rejects window activation (HCBT_ACTIVATE) unless the person at the computer is
physically clicking or holding Alt/Win. Hooks belong to a helper thread of this
process: they disappear when the gate stops or this process exits, and the DLL
itself goes inert three seconds after the last heartbeat.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
from pathlib import Path
import threading
import time

HERE = Path(__file__).resolve().parent
DLL_NAME = 'focus_gate_v6.dll'  # must match GATE_VERSION in focus_gate.c
DLL_PATH = HERE / DLL_NAME
WECHAT = {'weixin.exe', 'wechat.exe', 'wechatappex.exe', 'weixinappex.exe', 'wechatapp.exe'}
WH_CBT = 5
TH32CS_SNAPPROCESS, TH32CS_SNAPTHREAD = 0x2, 0x4
INVALID = C.c_void_p(-1).value

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)


def _sig(lib, name, args, res):
    f = getattr(lib, name); f.argtypes = args; f.restype = res; return f


class PROCESSENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                ('th32DefaultHeapID', C.c_size_t), ('th32ModuleID', W.DWORD), ('cntThreads', W.DWORD),
                ('th32ParentProcessID', W.DWORD), ('pcPriClassBase', C.c_long), ('dwFlags', W.DWORD),
                ('szExeFile', W.WCHAR * 260)]


class THREADENTRY32(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ThreadID', W.DWORD),
                ('th32OwnerProcessID', W.DWORD), ('tpBasePri', C.c_long), ('tpDeltaPri', C.c_long),
                ('dwFlags', W.DWORD)]


_sig(k, 'CreateToolhelp32Snapshot', [W.DWORD, W.DWORD], W.HANDLE)
_sig(k, 'Process32FirstW', [W.HANDLE, C.POINTER(PROCESSENTRY32W)], W.BOOL)
_sig(k, 'Process32NextW', [W.HANDLE, C.POINTER(PROCESSENTRY32W)], W.BOOL)
_sig(k, 'Thread32First', [W.HANDLE, C.POINTER(THREADENTRY32)], W.BOOL)
_sig(k, 'Thread32Next', [W.HANDLE, C.POINTER(THREADENTRY32)], W.BOOL)
_sig(k, 'CloseHandle', [W.HANDLE], W.BOOL)
_sig(k, 'ProcessIdToSessionId', [W.DWORD, C.POINTER(W.DWORD)], W.BOOL)
_sig(k, 'GetCurrentProcessId', [], W.DWORD)
_sig(u, 'SetWindowsHookExW', [C.c_int, C.c_void_p, W.HMODULE, W.DWORD], W.HANDLE)
_sig(u, 'UnhookWindowsHookEx', [W.HANDLE], W.BOOL)
_sig(u, 'GetForegroundWindow', [], W.HWND)
_sig(u, 'GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
_sig(u, 'PeekMessageW', [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)
_sig(u, 'DispatchMessageW', [C.POINTER(W.MSG)], W.LPARAM)
_sig(u, 'SetForegroundWindow', [W.HWND], W.BOOL)
_sig(u, 'IsWindow', [W.HWND], W.BOOL)
_sig(u, 'GetAsyncKeyState', [C.c_int], C.c_short)
_sig(u, 'GetCursorPos', [C.POINTER(W.POINT)], W.BOOL)
_sig(u, 'WindowFromPoint', [W.POINT], W.HWND)
_sig(u, 'GetAncestor', [W.HWND, W.UINT], W.HWND)
_sig(u, 'GetClassNameW', [W.HWND, W.LPWSTR, C.c_int], C.c_int)
_sig(u, 'RegisterHotKey', [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL)
_sig(u, 'UnregisterHotKey', [W.HWND, C.c_int], W.BOOL)
VK_F22, WM_HOTKEY, HOTKEY_ID = 0x85, 0x0312, 0xBABA
_sig(u, 'LockSetForegroundWindow', [W.UINT], W.BOOL)
_sig(u, 'SetWindowPos', [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL)
_sig(u, 'GetWindowRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL)
_sig(u, 'IsWindowVisible', [W.HWND], W.BOOL)
_sig(u, 'MonitorFromWindow', [W.HWND, W.DWORD], W.HMONITOR)


class MONITORINFO(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT), ('dwFlags', W.DWORD)]


_sig(u, 'GetMonitorInfoW', [W.HMONITOR, C.POINTER(MONITORINFO)], W.BOOL)
ENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
_sig(u, 'EnumWindows', [ENUMPROC, W.LPARAM], W.BOOL)
HWND_BOTTOM = W.HWND(1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x1, 0x2, 0x10, 0x200
PARK_VISIBLE_PX = 16  # a sliver stays on screen so Chromium keeps rendering the page


def top_windows(pids):
    found = []

    @ENUMPROC
    def cb(h, _):
        if u.IsWindowVisible(h) and window_pid(h) in pids:
            found.append(int(h))
        return True
    u.EnumWindows(cb, 0)
    return found


def park(h):
    """Put a WeChat window at the bottom of the z-order and slide it to the right edge of its monitor."""
    r = W.RECT()
    if not u.GetWindowRect(h, C.byref(r)):
        return None
    mi = MONITORINFO(); mi.cbSize = C.sizeof(mi)
    if not u.GetMonitorInfoW(u.MonitorFromWindow(h, 2), C.byref(mi)):
        return None
    x = mi.rcWork.right - PARK_VISIBLE_PX
    flags = SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    if r.left >= x:
        flags |= SWP_NOMOVE
    u.SetWindowPos(h, HWND_BOTTOM, x, max(r.top, mi.rcWork.top), 0, 0, flags)
    return {'hwnd': int(h), 'from': [r.left, r.top, r.right, r.bottom], 'x': x}
LSFW_LOCK, LSFW_UNLOCK = 1, 2
EVENTPROC = C.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)
_sig(u, 'SetWinEventHook', [W.DWORD, W.DWORD, W.HMODULE, EVENTPROC, W.DWORD, W.DWORD, W.DWORD], W.HANDLE)
_sig(u, 'UnhookWinEvent', [W.HANDLE], W.BOOL)
TASKBAR = {'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'XamlExplorerHostIslandWindow'}


def user_intent(pids):
    """Same rule as the DLL: Alt/Win held, or a mouse button held over WeChat or the taskbar."""
    if any(u.GetAsyncKeyState(vk) & 0x8000 for vk in (0x12, 0x5B, 0x5C)):
        return True
    if not any(u.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04)):
        return False
    pt = W.POINT()
    if not u.GetCursorPos(C.byref(pt)):
        return False
    h = u.WindowFromPoint(pt)
    root = u.GetAncestor(h, 2) if h else None
    if not root:
        return False
    if window_pid(root) in pids:
        return True
    buf = C.create_unicode_buffer(64); u.GetClassNameW(root, buf, 64)
    return buf.value in TASKBAR


def dll_sha256():
    return hashlib.sha256(DLL_PATH.read_bytes()).hexdigest()


def _session(pid):
    s = W.DWORD()
    return s.value if k.ProcessIdToSessionId(pid, C.byref(s)) else None


def wechat_pids():
    """WeChat process ids in this logon session."""
    me = _session(k.GetCurrentProcessId())
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID:
        raise C.WinError(C.get_last_error())
    found = set()
    try:
        e = PROCESSENTRY32W(); e.dwSize = C.sizeof(e)
        ok = k.Process32FirstW(snap, C.byref(e))
        while ok:
            if e.szExeFile.lower() in WECHAT and _session(e.th32ProcessID) == me:
                found.add(int(e.th32ProcessID))
            ok = k.Process32NextW(snap, C.byref(e))
    finally:
        k.CloseHandle(snap)
    return found


def threads_of(pids):
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == INVALID:
        raise C.WinError(C.get_last_error())
    found = set()
    try:
        e = THREADENTRY32(); e.dwSize = C.sizeof(e)
        ok = k.Thread32First(snap, C.byref(e))
        while ok:
            if e.th32OwnerProcessID in pids:
                found.add((int(e.th32OwnerProcessID), int(e.th32ThreadID)))
            ok = k.Thread32Next(snap, C.byref(e))
    finally:
        k.CloseHandle(snap)
    return found


def window_pid(h):
    pid = W.DWORD()
    if h:
        u.GetWindowThreadProcessId(h, C.byref(pid))
    return int(pid.value)


def _load():
    if C.sizeof(C.c_void_p) != 8:
        raise RuntimeError('Activation gate requires 64-bit Python')
    if not DLL_PATH.exists():
        raise RuntimeError(DLL_NAME + ' missing; run build_focus_gate.ps1')
    dll = C.WinDLL(str(DLL_PATH), use_last_error=True)
    _sig(dll, 'Configure', [], W.BOOL)
    _sig(dll, 'AddPid', [W.DWORD], W.BOOL)
    _sig(dll, 'Pulse', [], W.BOOL)
    _sig(dll, 'Stats', [C.POINTER(W.LONG), C.POINTER(W.LONG), C.POINTER(C.c_longlong)], W.BOOL)
    _sig(dll, 'Shutdown', [], None)
    _sig(dll, 'SetReturnWindow', [W.HWND], W.BOOL)
    _sig(dll, 'Returned', [], W.LONG)
    _sig(dll, 'LostSeen', [], W.LONG)
    _sig(dll, 'ApiBlocked', [], W.LONG)
    _sig(dll, 'DeniedBy', [C.POINTER(W.LONG * 6)], W.BOOL)
    _sig(dll, 'Trace', [W.LPWSTR, C.c_int], W.BOOL)
    _sig(dll, 'LostDetail', [C.POINTER(C.c_longlong), C.POINTER(C.c_longlong), C.POINTER(W.LONG), C.POINTER(W.LONG)], W.BOOL)
    _sig(dll, 'ApiPatched', [], W.LONG)
    return dll


class ActivationGate:
    """Context manager. `pids` overrides WeChat discovery (tests only)."""

    def __init__(self, pids=None, rescan=True, park_new=True):
        self.park_new = park_new
        self.fixed = set(pids) if pids is not None else None
        self.rescan = rescan and pids is None
        self.report = {}
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = None

    def _targets(self):
        return set(self.fixed) if self.fixed is not None else wechat_pids()

    def _run(self):
        dll = None; hooks = {}; hotkey = False; event_hook = None; locked = False
        rep = self.report
        rep['foreground_events'] = []

        @EVENTPROC
        def on_foreground(hook, event, hwnd, obj, child, tid, ms):
            rep['foreground_events'].append({'at': time.time(), 'hwnd': int(hwnd or 0), 'pid': window_pid(hwnd)})
        self._event_proc = on_foreground
        try:
            dll = _load()
            if not dll.Configure():
                raise RuntimeError('Another activation gate is active; operations must be serial')
            # Chromium obtains foreground rights by registering F22 as a hotkey and injecting
            # an F22 press. Holding that hotkey here makes the trick deliver to this thread,
            # so WeChat never gains the right to take the foreground.
            hotkey = bool(u.RegisterHotKey(None, HOTKEY_ID, 0, VK_F22))
            rep.update(f22_hotkey_held=hotkey, f22_presses_absorbed=0)
            # Agent tools inherit foreground rights from whichever app launched them and UIA can
            # pass those rights to WeChat. The system foreground lock refuses every programmatic
            # foreground change; any key press or click by the person releases it automatically.
            locked = bool(u.LockSetForegroundWindow(LSFW_LOCK))
            rep.update(foreground_lock=locked, foreground_lock_retries=0)
            # Queued, out-of-context EVENT_SYSTEM_FOREGROUND records every change, however brief.
            event_hook = u.SetWinEventHook(3, 3, None, on_foreground, 0, 0, 0)
            proc = C.cast(dll.FocusGateProc, C.c_void_p)
            pids = set(); failed = set()

            def sync():
                for pid in self._targets() - pids:
                    if not dll.AddPid(pid):
                        raise C.WinError(C.get_last_error())
                    pids.add(pid)
                for key in threads_of(pids) - hooks.keys() - failed:
                    h = u.SetWindowsHookExW(WH_CBT, proc, dll._handle, key[1])
                    if h: hooks[key] = h
                    else: failed.add(key)

            dll.Pulse()
            sync()
            if not hooks:
                raise RuntimeError('No WeChat thread could be guarded')
            fg0 = u.GetForegroundWindow()
            rep.update(pids=sorted(pids), foreground_before=int(fg0 or 0), foreground_changes=[],
                       foreground_returned=[], parked_windows=[], hooked_threads=len(hooks), dll_sha256=dll_sha256())
            known = set(top_windows(pids))
            self._ready.set()
            # Window the person is using; WeChat windows are never recorded here.
            user_fg = fg0 if fg0 and window_pid(fg0) not in pids else None
            dll.SetReturnWindow(user_fg)
            last = fg0; msg = W.MSG(); last_scan = time.monotonic()
            blocked = W.LONG(); allowed = W.LONG(); last_h = C.c_longlong()
            seen_blocked = 0; blocked_at = None; lost_at = None
            while not self._stop.is_set():
                dll.Pulse()
                while u.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                    if msg.message == WM_HOTKEY:
                        rep['f22_presses_absorbed'] += 1
                        if not locked:  # receiving the hotkey grants this thread the right to lock
                            locked = bool(u.LockSetForegroundWindow(LSFW_LOCK))
                            rep['foreground_lock_retries'] += 1; rep['foreground_lock'] = locked
                    u.DispatchMessageW(C.byref(msg))
                if self.rescan and time.monotonic() - last_scan > .05:
                    sync(); last_scan = time.monotonic()
                if self.park_new:
                    for h in set(top_windows(pids)) - known:
                        known.add(h)
                        if not user_intent(pids):
                            info = park(h)
                            if info:
                                rep['parked_windows'].append(info)
                dll.Stats(C.byref(blocked), C.byref(allowed), C.byref(last_h))
                if blocked.value != seen_blocked:
                    seen_blocked = blocked.value; blocked_at = time.monotonic()
                fg = u.GetForegroundWindow()
                now = time.monotonic()
                if fg != last:
                    pid = window_pid(fg)
                    rep['foreground_changes'].append({'at': time.time(), 'hwnd': int(fg or 0), 'pid': pid,
                                                      'wechat': pid in pids})
                    last = fg
                    lost_at = now if (not fg or pid in pids) else None
                    if fg and pid not in pids:
                        user_fg = fg
                    elif fg and pid in pids and user_intent(pids):
                        user_fg = None  # the person chose WeChat; never pull them back
                    dll.SetReturnWindow(user_fg)
                # A rejected WeChat activation can leave no foreground window. Hand the
                # foreground straight back to the window the person was using.
                if (lost_at is not None and user_fg and blocked_at is not None and now - blocked_at < 2
                        and not user_intent(pids) and u.IsWindow(user_fg)):
                    if u.SetForegroundWindow(user_fg):
                        rep['foreground_returned'].append({'gap_ms': round((time.monotonic() - lost_at) * 1000, 1),
                                                           'hwnd': int(user_fg)})
                        lost_at = None
                time.sleep(.002)
        except Exception as exc:  # reported to the caller thread
            self._error = exc
            self._ready.set()
        finally:
            for h in hooks.values():
                u.UnhookWindowsHookEx(h)
            if locked:
                u.LockSetForegroundWindow(LSFW_UNLOCK)
            if hotkey:
                u.UnregisterHotKey(None, HOTKEY_ID)
            if event_hook:
                msg = W.MSG()
                while u.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                    u.DispatchMessageW(C.byref(msg))
                u.UnhookWinEvent(event_hook)
            if dll:
                b, a, last_h = W.LONG(), W.LONG(), C.c_longlong()
                if dll.Stats(C.byref(b), C.byref(a), C.byref(last_h)):
                    rep.update(blocked_activations=b.value, user_activations_allowed=a.value,
                               last_blocked_hwnd=last_h.value, returned_in_hook=dll.Returned(),
                               foreground_lost_in_hook=dll.LostSeen(), foreground_calls_denied=dll.ApiBlocked(),
                               import_slots_patched=dll.ApiPatched())
                buf = C.create_unicode_buffer(2048)
                if dll.Trace(buf, 2048) and buf.value:
                    rep['lost_trace'] = buf.value
                by = (W.LONG * 6)()
                if dll.DeniedBy(C.byref(by)):
                    rep['denied_by_api'] = dict(zip(['SetForegroundWindow', 'SwitchToThisWindow', 'SetActiveWindow',
                                                     'BringWindowToTop', 'SetFocus', 'SetWindowPos'], list(by)))
                lf, la, lp, lw = C.c_longlong(), C.c_longlong(), W.LONG(), W.LONG()
                if dll.LostDetail(C.byref(lf), C.byref(la), C.byref(lp), C.byref(lw)):
                    rep['lost_detail'] = {'foreground': lf.value, 'foreground_thread_active': la.value,
                                          'foreground_thread_pid': lp.value, 'wechat_thread_was_foreground': lw.value}
                dll.Shutdown()
            rep['hooked_threads_final'] = len(hooks)
            rep['foreground_after'] = int(u.GetForegroundWindow() or 0)

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, name='wechat-activation-gate', daemon=True)
        self._thread.start()
        if not self._ready.wait(10):
            self._stop.set(); raise RuntimeError('Activation gate did not start')
        if self._error:
            self._thread.join(5); raise RuntimeError('Activation gate unavailable: %s' % self._error)
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(10)
        if self._error and not exc[0]:
            raise RuntimeError('Activation gate failed during the action: %s' % self._error)
        rep = self.report
        pids = set(rep.get('pids', []))
        rep['wechat_foreground_events'] = sum(1 for e in rep.get('foreground_events', []) if e['pid'] in pids)
        rep['wechat_took_foreground'] = (any(c['wechat'] for c in rep.get('foreground_changes', []))
                                         or rep['wechat_foreground_events'] > 0) \
            and not rep.get('user_activations_allowed')
        rep['user_foreground_disturbed'] = bool(rep.get('foreground_lost_in_hook') or rep['wechat_took_foreground']
                                                or any(not c['hwnd'] or c['wechat'] for c in rep.get('foreground_changes', [])))
        changes = rep.get('foreground_changes', [])
        rep['foreground_lost_ms'] = None
        if changes:
            lost = [c for c in changes if not c['hwnd'] or c['wechat']]
            if lost:
                back = [c for c in changes if c['at'] > lost[0]['at'] and c['hwnd'] and not c['wechat']]
                rep['foreground_lost_ms'] = round(((back[0]['at'] if back else time.time()) - lost[0]['at']) * 1000, 1)
        return False

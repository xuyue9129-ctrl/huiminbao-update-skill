"""Activation-gate self test on a hidden window in a child process; never touches WeChat."""
import json
import subprocess
import sys
import textwrap
import unittest

import focus_gate as g

CHILD = textwrap.dedent(r'''
    import ctypes as C, sys, json
    from ctypes import wintypes as W
    u = C.WinDLL('user32', use_last_error=True)
    u.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
    u.CreateWindowExW.restype = W.HWND
    u.SetActiveWindow.argtypes = [W.HWND]; u.SetActiveWindow.restype = W.HWND
    u.GetActiveWindow.restype = W.HWND
    u.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
    u.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
    WS_POPUP = 0x80000000
    a = u.CreateWindowExW(0x80, 'STATIC', 'gate-test-a', WS_POPUP, -32000, -32000, 10, 10, None, None, None, None)
    b = u.CreateWindowExW(0x80, 'STATIC', 'gate-test-b', WS_POPUP, -32000, -32000, 10, 10, None, None, None, None)
    print(json.dumps({'ready': True}), flush=True)
    for line in sys.stdin:
        target = a if line.strip() == 'a' else b
        u.SetActiveWindow(target)
        msg = W.MSG()
        while u.PeekMessageW(C.byref(msg), None, 0, 0, 1): u.DispatchMessageW(C.byref(msg))
        active = u.GetActiveWindow()
        print(json.dumps({'requested': line.strip(), 'active_is_target': active == target}), flush=True)
''')


class GateTests(unittest.TestCase):
    def ask(self, p, which):
        p.stdin.write(which + '\n'); p.stdin.flush()
        return json.loads(p.stdout.readline())

    def test_gate_blocks_activation_only_while_enabled(self):
        p = subprocess.Popen([sys.executable, '-c', CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            # The child inherits this process's foreground rights, so every activation it
            # attempts must happen inside the gate or it could take the user's foreground.
            self.assertTrue(json.loads(p.stdout.readline())['ready'])
            with g.ActivationGate(pids={p.pid}) as gate:
                first = self.ask(p, 'a')
                second = self.ask(p, 'b')
            self.assertFalse(first['active_is_target'] or second['active_is_target'],
                             'activation must be rejected while gated')
            self.assertGreaterEqual(gate.report['blocked_activations'], 2)
            self.assertEqual(gate.report['hooked_threads_final'], gate.report['hooked_threads'])
            self.assertFalse(gate.report['wechat_took_foreground'])
            self.assertNotIn(int(g.u.GetForegroundWindow() or 0), gate.report['pids'])
        finally:
            p.kill(); p.wait(5); p.stdin.close(); p.stdout.close()

    def test_gate_is_serial(self):
        with g.ActivationGate(pids={g.k.GetCurrentProcessId()}):
            with self.assertRaisesRegex(RuntimeError, 'Another activation gate'):
                with g.ActivationGate(pids={g.k.GetCurrentProcessId()}):
                    pass

    def test_wechat_discovery_is_names_only(self):
        for pid in g.wechat_pids():
            self.assertIsInstance(pid, int)


if __name__ == '__main__':
    unittest.main(verbosity=2)

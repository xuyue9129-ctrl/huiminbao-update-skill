"""Verify private window messages on an invisible test control, never on WeChat."""
import ctypes as C
from ctypes import wintypes as W
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import control as b


class BackgroundTests(unittest.TestCase):
    def test_source_url_redaction(self):
        query=urlencode({'__biz':'abc','mid':'10','idx':'1','sn':'ok','key':'SECRET','pass_ticket':'SECRET2'})
        cleaned=b.sanitize('URL: https://mp.weixin.qq.com/s?'+query)
        self.assertNotIn('SECRET',cleaned)
        self.assertIn('sn=ok',cleaned)
        self.assertIn('mid=10',cleaned)

    def test_main_window_guard_denies_action(self):
        with patch.object(b,'inspect',return_value={'foreground':False,'minimized':False,'process':'Weixin.exe'}):
            with self.assertRaisesRegex(RuntimeError,'research'):
                with b.guard(987654321): self.fail('Must not permit main chat input')

    def test_coordinates_and_unicode(self):
        self.assertEqual(b.xy(-1,2),0x2ffff)
        with self.assertRaises(ValueError): b.xy(100000,0)
        self.assertEqual(b.char_units('A🤖'),[65,0xd83e,0xdd16])

    def test_foreground_guard_denies_action(self):
        reached=False
        with patch.object(b,'inspect',return_value={'foreground':True,'minimized':False}):
            with self.assertRaisesRegex(RuntimeError,'foreground'):
                with b.guard(987654321): reached=True
        self.assertFalse(reached)

    def test_window_guard_rejects_nonwechat(self):
        with patch.object(b.u,'IsWindow',return_value=True),patch.object(b,'process',return_value=(1,'notepad.exe')):
            with self.assertRaisesRegex(ValueError,'WeChat'): b.inspect(456789)

    def test_hidden_edit_receives_unicode_without_focus(self):
        b.sig(b.u,'CreateWindowExW',[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p],W.HWND)
        b.sig(b.u,'DestroyWindow',[W.HWND],W.BOOL)
        b.sig(b.u,'PeekMessageW',[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT],W.BOOL)
        b.sig(b.u,'DispatchMessageW',[C.POINTER(W.MSG)],W.LPARAM)
        parent=b.u.CreateWindowExW(0,'STATIC','hidden-wechat-skill-test',0,0,0,400,100,None,None,None,None)
        self.assertTrue(parent)
        child=b.u.CreateWindowExW(0,'EDIT','',0x40000000,0,0,300,40,parent,None,None,None)
        self.assertTrue(child)
        before=int(b.u.GetForegroundWindow() or 0)
        try:
            self.assertFalse(b.u.IsWindowVisible(parent))
            text='后台测试🤖'
            for unit in b.char_units(text): b.post(child,0x102,unit,1)
            msg=W.MSG(); deadline=time.monotonic()+.5
            while time.monotonic()<deadline:
                while b.u.PeekMessageW(C.byref(msg),None,0,0,1): b.u.DispatchMessageW(C.byref(msg))
                if b.title(child)==text: break
                time.sleep(.01)
            self.assertEqual(b.title(child),text)
            self.assertNotIn(b.u.GetForegroundWindow(),[parent,child])
            print(json.dumps({'hidden_control_input':'passed','foreground_before':before,'foreground_after':int(b.u.GetForegroundWindow() or 0),'visible_test_window':False}))
        finally:
            b.u.DestroyWindow(parent)


if __name__=='__main__': unittest.main(verbosity=2)

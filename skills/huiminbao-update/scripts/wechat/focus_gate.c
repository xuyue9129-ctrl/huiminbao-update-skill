/* Activation gate for WeChat research windows.
 * Installed per thread (WH_CBT) only on threads of WeChat processes listed in shared memory.
 * Only HCBT_ACTIVATE is examined; no input, message content or window text is read. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <psapi.h>
#include <delayimp.h>

#define GATE_VERSION 6
#define GATE_MAGIC 0x57584732
#define MAX_PIDS 64
#define HEARTBEAT_MS 3000

typedef struct {
    LONG magic;
    volatile LONG enabled;
    volatile LONG64 heartbeat;
    volatile LONG pid_count;
    DWORD pids[MAX_PIDS];
    volatile LONG blocked;
    volatile LONG allowed_user;
    volatile LONG64 last_blocked_hwnd;
    volatile LONG64 return_hwnd;
    volatile LONG returned;
    volatile LONG lost_seen;
    volatile LONG api_blocked;
    volatile LONG api_patched;
    volatile LONG64 generation;
    volatile LONG64 lost_fg;          /* GetForegroundWindow() seen when a loss was counted */
    volatile LONG lost_fg_pid;        /* process owning the foreground thread at that moment */
    volatile LONG64 lost_fg_active;   /* active window of the foreground thread */
    volatile LONG lost_in_wechat_thread; /* foreground thread was the hooked WeChat thread */
    volatile LONG api_denied_by[6];
    volatile LONG trace_taken;
    WCHAR trace[2048];                /* module+offset frames for the first lost-foreground activation */   /* SetForegroundWindow, SwitchToThisWindow, SetActiveWindow, BringWindowToTop, SetFocus, SetWindowPos */
} Gate;

/* Bump the version whenever Gate changes: a pinned older DLL must never read a newer layout. */
static const WCHAR map_name[] = L"Local\\WeChatResearchActivationGate_v6_4f0c2d7a";
static HANDLE map_handle;
static Gate *gate;
static BOOL owner;

static BOOL connect_gate(void) {
    if (gate) return TRUE;
    HANDLE h = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, map_name);
    if (!h) return FALSE;
    Gate *g = (Gate *)MapViewOfFile(h, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(Gate));
    if (!g) { CloseHandle(h); return FALSE; }
    map_handle = h; gate = g;
    return TRUE;
}

static BOOL fresh(void) {
    return gate && gate->magic == GATE_MAGIC && gate->enabled &&
           GetTickCount64() - (ULONGLONG)gate->heartbeat < HEARTBEAT_MS;
}

__declspec(dllexport) BOOL WINAPI Configure(void) {
    map_handle = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, sizeof(Gate), map_name);
    if (!map_handle) return FALSE;
    BOOL existed = GetLastError() == ERROR_ALREADY_EXISTS;
    gate = (Gate *)MapViewOfFile(map_handle, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(Gate));
    if (!gate) { CloseHandle(map_handle); map_handle = NULL; return FALSE; }
    if (existed && fresh()) {
        UnmapViewOfFile(gate); CloseHandle(map_handle); gate = NULL; map_handle = NULL;
        SetLastError(ERROR_BUSY); return FALSE;
    }
    ZeroMemory(gate, sizeof(Gate));
    gate->magic = GATE_MAGIC;
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    gate->generation = now.QuadPart;
    owner = TRUE;
    return TRUE;
}

__declspec(dllexport) BOOL WINAPI AddPid(DWORD pid) {
    if (!owner || !gate) return FALSE;
    LONG n = gate->pid_count;
    for (LONG i = 0; i < n; ++i) if (gate->pids[i] == pid) return TRUE;
    if (n >= MAX_PIDS) { SetLastError(ERROR_INSUFFICIENT_BUFFER); return FALSE; }
    gate->pids[n] = pid;
    MemoryBarrier();
    InterlockedExchange(&gate->pid_count, n + 1);
    return TRUE;
}

__declspec(dllexport) BOOL WINAPI Pulse(void) {
    if (!owner || !gate) return FALSE;
    InterlockedExchange64(&gate->heartbeat, (LONG64)GetTickCount64());
    InterlockedExchange(&gate->enabled, 1);
    return TRUE;
}

/* Window the person was using; 0 disables hand-back. Set only by the controller. */
__declspec(dllexport) BOOL WINAPI SetReturnWindow(HWND h) {
    if (!owner || !gate) return FALSE;
    InterlockedExchange64(&gate->return_hwnd, (LONG64)(uintptr_t)h);
    return TRUE;
}

__declspec(dllexport) LONG WINAPI Returned(void) { return gate ? gate->returned : 0; }
__declspec(dllexport) LONG WINAPI LostSeen(void) { return gate ? gate->lost_seen : 0; }
__declspec(dllexport) BOOL WINAPI LostDetail(LONG64 *fg, LONG64 *active, LONG *pid, LONG *in_wechat) {
    if (!gate) return FALSE;
    *fg = gate->lost_fg; *active = gate->lost_fg_active; *pid = gate->lost_fg_pid; *in_wechat = gate->lost_in_wechat_thread;
    return TRUE;
}

__declspec(dllexport) BOOL WINAPI DeniedBy(LONG *out6) {
    if (!gate) return FALSE;
    for (int i = 0; i < 6; ++i) out6[i] = gate->api_denied_by[i];
    return TRUE;
}

__declspec(dllexport) BOOL WINAPI Trace(WCHAR *out, int size) {
    if (!gate || size <= 0) return FALSE;
    lstrcpynW(out, gate->trace, size);
    return TRUE;
}

__declspec(dllexport) LONG WINAPI ApiBlocked(void) { return gate ? gate->api_blocked : 0; }
__declspec(dllexport) LONG WINAPI ApiPatched(void) { return gate ? gate->api_patched : 0; }

__declspec(dllexport) BOOL WINAPI Stats(LONG *blocked, LONG *allowed_user, LONG64 *last_hwnd) {
    if (!gate) return FALSE;
    *blocked = gate->blocked; *allowed_user = gate->allowed_user; *last_hwnd = gate->last_blocked_hwnd;
    return TRUE;
}

__declspec(dllexport) void WINAPI Shutdown(void) {
    if (gate) { InterlockedExchange(&gate->enabled, 0); UnmapViewOfFile(gate); gate = NULL; }
    if (map_handle) { CloseHandle(map_handle); map_handle = NULL; }
    owner = FALSE;
}

static BOOL listed(HWND h) {
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    LONG n = gate->pid_count;
    if (n > MAX_PIDS) n = MAX_PIDS;
    for (LONG i = 0; i < n; ++i) if (gate->pids[i] == pid) return TRUE;
    return FALSE;
}

/* Physical intent from the person at the keyboard: Alt/Win held (Alt+Tab, Win+number) or a
 * mouse button held over a WeChat window or the taskbar. Posted window messages do not
 * change this asynchronous key state. */
static BOOL pointer_on_wechat_or_taskbar(void) {
    POINT pt;
    if (!GetCursorPos(&pt)) return FALSE;
    HWND h = WindowFromPoint(pt);
    if (!h) return FALSE;
    HWND root = GetAncestor(h, GA_ROOT);
    if (listed(root ? root : h)) return TRUE;
    WCHAR cls[64];
    if (!GetClassNameW(root ? root : h, cls, 64)) return FALSE;
    return lstrcmpW(cls, L"Shell_TrayWnd") == 0 || lstrcmpW(cls, L"Shell_SecondaryTrayWnd") == 0 ||
           lstrcmpW(cls, L"XamlExplorerHostIslandWindow") == 0;
}

static BOOL user_intent(void) {
    static const int keys[] = {VK_MENU, VK_LWIN, VK_RWIN};
    for (unsigned i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i)
        if (GetAsyncKeyState(keys[i]) & 0x8000) return TRUE;
    if ((GetAsyncKeyState(VK_LBUTTON) | GetAsyncKeyState(VK_RBUTTON) | GetAsyncKeyState(VK_MBUTTON)) & 0x8000)
        return pointer_on_wechat_or_taskbar();
    return FALSE;
}

/* ---- In-process interception of foreground requests (WeChat processes only) ----
 * The CBT hook runs only after Windows has already moved the foreground queue. To stop the
 * move itself, import-table entries for SetForegroundWindow/SwitchToThisWindow in WeChat
 * modules point at the stubs below. Outside an active gate they call straight through. */
typedef BOOL (WINAPI *SetFg)(HWND);
typedef void (WINAPI *SwitchTo)(HWND, BOOL);
typedef HWND (WINAPI *HwndFn)(HWND);
typedef BOOL (WINAPI *SetPos)(HWND, HWND, int, int, int, int, UINT);
static SetFg real_set_fg;
static SwitchTo real_switch_to;
static HwndFn real_set_active, real_set_focus;
static SetFg real_bring_top;
static SetPos real_set_pos;
static HMODULE self_module;
static volatile LONG local_patched;

static BOOL deny_foreground(HWND h, int api) {
    if (!connect_gate() || !fresh() || !h || !listed(h) || user_intent()) return FALSE;
    InterlockedIncrement(&gate->api_blocked);
    InterlockedIncrement(&gate->api_denied_by[api]);
    return TRUE;
}

/* True when activating h's top-level window would move the system foreground. */
static BOOL would_activate(HWND h) {
    HWND root = GetAncestor(h, GA_ROOT);
    HWND fg = GetForegroundWindow();
    return root && root != fg && root != GetActiveWindow();
}

static BOOL WINAPI gate_SetForegroundWindow(HWND h) {
    if (deny_foreground(h, 0)) { SetLastError(ERROR_ACCESS_DENIED); return FALSE; }
    return real_set_fg(h);
}

static void WINAPI gate_SwitchToThisWindow(HWND h, BOOL alt_tab) {
    if (deny_foreground(h, 1)) return;
    real_switch_to(h, alt_tab);
}

static HWND WINAPI gate_SetActiveWindow(HWND h) {
    if (would_activate(h) && deny_foreground(h, 2)) return GetActiveWindow();
    return real_set_active(h);
}

static BOOL WINAPI gate_BringWindowToTop(HWND h) {
    if (would_activate(h) && deny_foreground(h, 3)) return TRUE;
    return real_bring_top(h);
}

/* Focus inside an already active top-level window is untouched; only a focus change that
 * would first activate another top-level window is refused. */
static HWND WINAPI gate_SetFocus(HWND h) {
    if (h && would_activate(h) && deny_foreground(h, 4)) return GetFocus();
    return real_set_focus(h);
}

static BOOL WINAPI gate_SetWindowPos(HWND h, HWND after, int x, int y, int cx, int cy, UINT flags) {
    if (!(flags & SWP_NOACTIVATE) && GetAncestor(h, GA_ROOT) == h && would_activate(h) && deny_foreground(h, 5))
        flags |= SWP_NOACTIVATE;
    return real_set_pos(h, after, x, y, cx, cy, flags);
}

static void *replacement(const char *name, ULONG_PTR current) {
    if ((name && !lstrcmpA(name, "SetForegroundWindow")) || current == (ULONG_PTR)real_set_fg)
        return (void *)gate_SetForegroundWindow;
    if ((name && !lstrcmpA(name, "SwitchToThisWindow")) || current == (ULONG_PTR)real_switch_to)
        return (void *)gate_SwitchToThisWindow;
    if ((name && !lstrcmpA(name, "SetActiveWindow")) || current == (ULONG_PTR)real_set_active)
        return (void *)gate_SetActiveWindow;
    if ((name && !lstrcmpA(name, "BringWindowToTop")) || current == (ULONG_PTR)real_bring_top)
        return (void *)gate_BringWindowToTop;
    if ((name && !lstrcmpA(name, "SetFocus")) || current == (ULONG_PTR)real_set_focus)
        return (void *)gate_SetFocus;
    if ((name && !lstrcmpA(name, "SetWindowPos")) || current == (ULONG_PTR)real_set_pos)
        return (void *)gate_SetWindowPos;
    return NULL;
}

static void write_slot(ULONG_PTR *slot, void *value) {
    DWORD old;
    if (*slot == (ULONG_PTR)value) return;
    if (VirtualProtect(slot, sizeof(*slot), PAGE_READWRITE, &old)) {
        InterlockedExchangePointer((PVOID *)slot, value);
        VirtualProtect(slot, sizeof(*slot), old, &old);
        InterlockedIncrement(&local_patched);
    }
}

static void patch_table(BYTE *base, DWORD names_rva, DWORD slots_rva) {
    IMAGE_THUNK_DATA *names = (IMAGE_THUNK_DATA *)(base + (names_rva ? names_rva : slots_rva));
    IMAGE_THUNK_DATA *slots = (IMAGE_THUNK_DATA *)(base + slots_rva);
    for (; slots->u1.Function; ++names, ++slots) {
        const char *name = NULL;
        if (names_rva && !IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))
            name = (const char *)((IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData))->Name;
        void *to = replacement(name, slots->u1.Function);
        if (to) write_slot((ULONG_PTR *)&slots->u1.Function, to);
    }
}

static void patch_module(HMODULE module) {
    BYTE *base = (BYTE *)module;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (module == self_module || dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return;
    IMAGE_DATA_DIRECTORY *dirs = nt->OptionalHeader.DataDirectory;
    if (dirs[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress) {
        IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dirs[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
        for (; d->Name; ++d)
            if (!lstrcmpiA((const char *)(base + d->Name), "user32.dll"))
                patch_table(base, d->OriginalFirstThunk, d->FirstThunk);
    }
    if (dirs[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT].VirtualAddress) {
        IMAGE_DELAYLOAD_DESCRIPTOR *d = (IMAGE_DELAYLOAD_DESCRIPTOR *)(base + dirs[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT].VirtualAddress);
        for (; d->DllNameRVA; ++d)
            if (!lstrcmpiA((const char *)(base + d->DllNameRVA), "user32.dll"))
                patch_table(base, d->ImportNameTableRVA, d->ImportAddressTableRVA);
    }
}

static BOOL wechat_process(void) {
    WCHAR path[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return FALSE;
    const WCHAR *exe = path;
    for (const WCHAR *p = path; *p; ++p) if (*p == L'\\') exe = p + 1;
    return !lstrcmpiW(exe, L"Weixin.exe") || !lstrcmpiW(exe, L"WeChat.exe") || !lstrcmpiW(exe, L"WeChatAppEx.exe") ||
           !lstrcmpiW(exe, L"WeixinAppEx.exe") || !lstrcmpiW(exe, L"WeChatApp.exe");
}

static void patch_process(void) {
    HMODULE user32 = GetModuleHandleW(L"user32.dll"), pinned, modules[1024];
    DWORD needed = 0;
    if (!user32) return;
    real_set_fg = (SetFg)GetProcAddress(user32, "SetForegroundWindow");
    real_switch_to = (SwitchTo)GetProcAddress(user32, "SwitchToThisWindow");
    real_set_active = (HwndFn)GetProcAddress(user32, "SetActiveWindow");
    real_set_focus = (HwndFn)GetProcAddress(user32, "SetFocus");
    real_bring_top = (SetFg)GetProcAddress(user32, "BringWindowToTop");
    real_set_pos = (SetPos)GetProcAddress(user32, "SetWindowPos");
    if (!real_set_fg || !real_switch_to || !real_set_active || !real_set_focus || !real_bring_top || !real_set_pos) return;
    /* Import slots may point here after the hook is removed, so this DLL must stay loaded
     * for the life of the process. The stubs are inert without a live gate. */
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN | GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
                            (LPCWSTR)(void *)gate_SetForegroundWindow, &pinned)) return;
    if (!K32EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed)) return;
    DWORD count = needed / sizeof(HMODULE);
    if (count > 1024) count = 1024;
    for (DWORD i = 0; i < count; ++i) patch_module(modules[i]);
}

__declspec(dllexport) LRESULT CALLBACK FocusGateProc(int code, WPARAM wparam, LPARAM lparam) {
    static volatile LONG64 reported_generation;
    if (local_patched && connect_gate() && gate->magic == GATE_MAGIC) {
        LONG64 g = gate->generation;
        if (InterlockedExchange64(&reported_generation, g) != g) InterlockedExchangeAdd(&gate->api_patched, local_patched);
    }
    if (code == HCBT_ACTIVATE && connect_gate() && fresh() && listed((HWND)wparam)) {
        if (user_intent()) {
            InterlockedIncrement(&gate->allowed_user);
        } else {
            InterlockedIncrement(&gate->blocked);
            InterlockedExchange64(&gate->last_blocked_hwnd, (LONG64)(uintptr_t)wparam);
            /* WeChat already moved the system foreground to this thread before asking to
             * activate; while it holds that right, give the foreground straight back. */
            HWND back = (HWND)(uintptr_t)gate->return_hwnd;
            HWND fg = GetForegroundWindow();
            if (back && fg != back && (!fg || listed(fg))) {
                GUITHREADINFO gti = {sizeof(gti)};
                DWORD fg_pid = 0;
                if (GetGUIThreadInfo(0, &gti) && gti.hwndActive) GetWindowThreadProcessId(gti.hwndActive, &fg_pid);
                InterlockedExchange64(&gate->lost_fg, (LONG64)(uintptr_t)fg);
                InterlockedExchange64(&gate->lost_fg_active, (LONG64)(uintptr_t)gti.hwndActive);
                InterlockedExchange(&gate->lost_fg_pid, (LONG)fg_pid);
                GUITHREADINFO mine = {sizeof(mine)};
                if (GetGUIThreadInfo(GetCurrentThreadId(), &mine) && GetForegroundWindow() == NULL &&
                    gti.hwndActive == mine.hwndActive) InterlockedIncrement(&gate->lost_in_wechat_thread);
                InterlockedIncrement(&gate->lost_seen);
                if (!InterlockedExchange(&gate->trace_taken, 1)) {
                    void *frames[40];
                    USHORT n = RtlCaptureStackBackTrace(0, 40, frames, NULL);
                    int pos = 0;
                    for (USHORT i = 0; i < n && pos < 1900; ++i) {
                        HMODULE m = NULL; WCHAR name[MAX_PATH] = L"?";
                        if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                               (LPCWSTR)frames[i], &m) && m) {
                            WCHAR full[MAX_PATH];
                            if (GetModuleFileNameW(m, full, MAX_PATH)) {
                                const WCHAR *b = full; for (const WCHAR *q = full; *q; ++q) if (*q == L'\\') b = q + 1;
                                lstrcpynW(name, b, 64);
                            }
                        }
                        pos += wsprintfW(gate->trace + pos, L"%s+%Ix;", name, (ULONG_PTR)((BYTE *)frames[i] - (BYTE *)m));
                    }
                }
                if (IsWindow(back) && SetForegroundWindow(back)) InterlockedIncrement(&gate->returned);
            }
            return 1;
        }
    }
    return CallNextHookEx(NULL, code, wparam, lparam);
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        self_module = module;
        if (wechat_process()) patch_process();
    }
    if (reason == DLL_PROCESS_DETACH && !owner) {
        if (gate) UnmapViewOfFile(gate);
        if (map_handle) CloseHandle(map_handle);
    }
    return TRUE;
}

# Rebuild the activation-gate DLL (x64) from focus_gate.c with zig (pip install ziglang).
# WeChat keeps a loaded gate DLL pinned until it restarts, so every build that changes
# focus_gate.c must raise GATE_VERSION there and DLL_NAME in focus_gate.py together.
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'focus_gate.c'
$m = Select-String -Path $src -Pattern '#define GATE_VERSION (\d+)' | Select-Object -First 1
if (-not $m) { throw 'GATE_VERSION missing in focus_gate.c' }
$out = Join-Path $here ('focus_gate_v' + $m.Matches[0].Groups[1].Value + '.dll')
& $Python -m ziglang cc -shared -O2 -target x86_64-windows-gnu -o $out $src -luser32 -lkernel32
if ($LASTEXITCODE -ne 0) { throw 'zig build failed (a loaded DLL cannot be overwritten; raise GATE_VERSION)' }
Get-ChildItem $here -Filter 'focus_gate_v*.lib' | Remove-Item -ErrorAction SilentlyContinue
Get-ChildItem $here -Filter 'focus_gate_v*.pdb' | Remove-Item -ErrorAction SilentlyContinue
(Get-FileHash $out -Algorithm SHA256).Hash + '  ' + (Split-Path -Leaf $out)

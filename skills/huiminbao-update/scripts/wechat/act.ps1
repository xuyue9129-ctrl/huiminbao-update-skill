param([Int64]$Hwnd,[string]$Name,[string]$Type='',[string]$Action='find',[string]$Value='',[int]$Index=0,[switch]$Exact)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$A=[System.Windows.Automation.AutomationElement]
$root=$A::FromHandle([IntPtr]$Hwnd)
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$m=@()
foreach($e in $all){
  try{$c=$e.Current}catch{continue}
  $nm=$c.Name; $ct=$c.ControlType.ProgrammaticName -replace 'ControlType\.',''
  if($Type -and $ct -ne $Type){continue}
  if($Name -ne '*'){ if($Exact){ if($nm -ne $Name){continue} } elseif(-not $nm -or -not $nm.Contains($Name)){continue} }
  $m+= ,@($e,$ct,$nm)
}
if($Action -eq 'find'){ $i=0; foreach($x in $m){ $p=($x[0].GetSupportedPatterns()|%{$_.ProgrammaticName -replace 'PatternIdentifiers.Pattern',''}) -join ','; $r=$x[0].Current.BoundingRectangle; $extra=" rect=$($r.X),$($r.Y),$($r.Width),$($r.Height)"; if($x[1] -eq 'Edit'){ $v=$null; if($x[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$v)){ $extra+=" value=$($v.Current.Value)" } }; "$i $($x[1]) [$($x[2])] {$p}$extra"; $i++ }; return }
if($m.Count -le $Index){ "NOMATCH count=$($m.Count)"; exit 2 }
$e=$m[$Index][0]
function P($pat){ $o=$null; if($e.TryGetCurrentPattern($pat,[ref]$o)){return $o}; return $null }
switch($Action){
 'invoke' { $p=P ([System.Windows.Automation.InvokePattern]::Pattern); if($p){$p.Invoke();'invoked'} else { $l=P ([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern); if($l){$l.DoDefaultAction();'default-action'} else {'NO-INVOKE'; exit 3} } }
 'setvalue' { $p=P ([System.Windows.Automation.ValuePattern]::Pattern); if($p){$p.SetValue($Value);'set'} else {'NO-VALUE'; exit 3} }
 'select' { $p=P ([System.Windows.Automation.SelectionItemPattern]::Pattern); if($p){$p.Select();'selected'} else {'NO-SELECT'; exit 3} }
 'scrollinto' { $p=P ([System.Windows.Automation.ScrollItemPattern]::Pattern); if($p){$p.ScrollIntoView();'scrolled'} else {'NO-SCROLLITEM'; exit 3} }
 'legacy' { $l=P ([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern); if($l){$l.DoDefaultAction();'default-action'} else {'NO-LEGACY'; exit 3} }
}

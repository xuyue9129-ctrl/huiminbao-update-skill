param([Int64]$Hwnd,[double]$Set=-1,[double]$By=0)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
$cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document)
$docs=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
foreach($d in $docs){
  $rr=$d.Current.BoundingRectangle; if($d.Current.IsOffscreen -or $rr.IsEmpty -or $rr.Width -lt 100){continue}
  $o=$null
  if($d.TryGetCurrentPattern([System.Windows.Automation.ScrollPattern]::Pattern,[ref]$o)){
    if($Set -ge 0){ $o.SetScrollPercent(-1,$Set) }
    if($By -ne 0){ $v=[Math]::Min(100,[Math]::Max(0,$o.Current.VerticalScrollPercent+$By)); $o.SetScrollPercent(-1,$v) }
    "doc [$($d.Current.Name)] v=$($o.Current.VerticalScrollPercent) view=$($o.Current.VerticalViewSize) rect=$($d.Current.BoundingRectangle)"
  } else { "doc [$($d.Current.Name)] noscroll" }
}

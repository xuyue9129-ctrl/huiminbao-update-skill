param([Int64]$Hwnd,[string]$Out)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
$cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document)
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
$d=$null
foreach($x in $all){ $r=$x.Current.BoundingRectangle; if(-not $x.Current.IsOffscreen -and -not $r.IsEmpty -and $r.Width -gt 100){ $d=$x } }
if(-not $d -and $all.Count -gt 0){ $d=$all[$all.Count-1] }
if(-not $d){'NODOC';exit 2}
$sb=New-Object System.Text.StringBuilder
$v=$null; if($d.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$v)){[void]$sb.AppendLine("URL: "+$v.Current.Value)}
[void]$sb.AppendLine("TITLE: "+$d.Current.Name)
$w=[System.Windows.Automation.TreeWalker]::RawViewWalker
function Walk($e){
  $c=$e.Current; $ct=$c.ControlType.ProgrammaticName -replace 'ControlType\.',''
  if($ct -eq 'Text' -and $c.Name){ [void]$sb.AppendLine($c.Name); return }
  if($ct -eq 'Hyperlink'){ $o=$null; if($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$o) -and $o.Current.Value -notmatch '^javascript'){ [void]$sb.AppendLine("[LINK "+$c.Name+" -> "+$o.Current.Value+"]") } }
  if($ct -eq 'Image'){ [void]$sb.AppendLine("[IMG "+$c.Name+"]") }
  $ch=$w.GetFirstChild($e); while($ch -ne $null){ Walk $ch; $ch=$w.GetNextSibling($ch) }
}
Walk $d
[IO.File]::WriteAllText($Out,$sb.ToString(),[Text.Encoding]::UTF8)
"ok "+$sb.Length

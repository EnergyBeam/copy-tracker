param([string]$PythonPath, [string]$TaskName = 'CopyTracker-GMGN')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $PythonPath) { $PythonPath = (Get-Command pythonw.exe -ErrorAction Stop).Source }
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$account=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute $python -Argument ('"'+(Join-Path $root 'monitor.py')+'"') -WorkingDirectory $root
$logon=New-ScheduledTaskTrigger -AtLogOn -User $account
$watchdog=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($logon,$watchdog) -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State

<#
.SYNOPSIS
Writes a disabled, current-user publisher task for review. Never installs it.
.DESCRIPTION
Inputs are checked as paths only. Credentials and configuration contents are not
read. The generated task uses the existing local Python environment; no password
or administrator credential enters the XML. It runs only while this user is
logged on, so this is preparation for local supervision, not proof of 24/7 work.
This local-only helper is intentionally excluded from the VPS source archive.
Schema: https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-schema
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Workspace,
    [Parameter(Mandatory = $true)][string]$Config,
    [Parameter(Mandatory = $true)][string]$State,
    [Parameter(Mandatory = $true)][string]$EnvFile,
    [Parameter(Mandatory = $true)][string]$Output
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-InputPath([string]$Value, [string]$Kind) {
    $resolved = Resolve-Path -LiteralPath $Value -ErrorAction Stop
    if ($resolved.Provider.Name -ne 'FileSystem' -or
        -not (Test-Path -LiteralPath $resolved.ProviderPath -PathType $Kind)) {
        throw 'An existing filesystem path of the required type is needed.'
    }
    return $resolved.ProviderPath
}

function Quote-Argument([string]$Value) {
    # Task Scheduler Exec invokes Python directly, without a shell. Windows argv
    # parsing requires doubled trailing backslashes inside a quoted argument.
    if ($Value.Contains('"') -or $Value.Contains("`r") -or $Value.Contains("`n")) {
        throw 'Input paths cannot contain quotes or line breaks.'
    }
    return '"' + [regex]::Replace($Value, '(\\+)$', '$1$1') + '"'
}

$workspacePath = Resolve-InputPath $Workspace 'Container'
$pythonPath = Resolve-InputPath (Join-Path $workspacePath '.venv\Scripts\python.exe') 'Leaf'
$configPath = Resolve-InputPath $Config 'Leaf'
$statePath = Resolve-InputPath $State 'Container'
$envPath = Resolve-InputPath $EnvFile 'Leaf'
$outputPath = [IO.Path]::GetFullPath($Output)
if ([IO.Path]::GetExtension($outputPath) -ne '.xml' -or
    -not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($outputPath)) -PathType Container)) {
    throw 'Output must be a new .xml file in an existing directory.'
}

$arguments = '-m booking_bridge.pilot_supervisor --run --read-only --config ' +
    (Quote-Argument $configPath) + ' --state ' + (Quote-Argument $statePath) +
    ' --env-file ' + (Quote-Argument $envPath)
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$commandXml = [Security.SecurityElement]::Escape($pythonPath)
$argumentsXml = [Security.SecurityElement]::Escape($arguments)
$workspaceXml = [Security.SecurityElement]::Escape($workspacePath)

[xml]$document = @"
<?xml version="1.0" encoding="utf-8"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Prepared local read-only occupancy publisher. Disabled pending operational review.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>false</Enabled>
      <UserId>$sid</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="LocalPublisher">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <Enabled>false</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="LocalPublisher">
    <Exec>
      <Command>$commandXml</Command>
      <Arguments>$argumentsXml</Arguments>
      <WorkingDirectory>$workspaceXml</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$settings = New-Object System.Xml.XmlWriterSettings
$settings.Encoding = New-Object System.Text.UTF8Encoding($false)
$settings.Indent = $true
# CreateNew refuses to overwrite a config, secret, or previously reviewed task.
$stream = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $writer = [Xml.XmlWriter]::Create($stream, $settings)
    try { $document.Save($writer) }
    finally { $writer.Dispose() }
}
finally { $stream.Dispose() }

Write-Output 'Prepared disabled task XML. No task was registered or started.'

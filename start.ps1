$ErrorActionPreference = "Stop"

if (Test-Path (Join-Path $PSScriptRoot "start.local.ps1")) {
  . (Join-Path $PSScriptRoot "start.local.ps1")
}

$node = "C:\Users\jingjiang\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if (-not (Test-Path $node)) {
  throw "Node runtime not found: $node"
}

Set-Location $PSScriptRoot
& $node server.js

# ============================================================
# Obsidian 热门社区插件一键安装脚本
# 用法：在 PowerShell 中执行（管理员不需要，普通窗口即可）
#   .\scripts\install-obsidian-plugins.ps1
#   或指定仓库路径：.\scripts\install-obsidian-plugins.ps1 -VaultPath "D:\MyVault"
# ============================================================
param(
    [string]$VaultPath = "H:\ai-code-llmops\Obsidian\Obsidian"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 插件列表：显示名 + GitHub 仓库（按社区下载量排名，可自行增删）
$plugins = @(
    @{ Name = "Dataview";       Repo = "blacksmithgu/obsidian-dataview" },
    @{ Name = "Templater";      Repo = "SilentVoid13/Templater" },
    @{ Name = "Excalidraw";     Repo = "zsviczian/obsidian-excalidraw-plugin" },
    @{ Name = "Kanban";         Repo = "mgmeyers/obsidian-kanban" },
    @{ Name = "QuickAdd";       Repo = "chhoumann/quickadd" },
    @{ Name = "Obsidian Git";   Repo = "Vinzent03/obsidian-git" },
    @{ Name = "Calendar";       Repo = "liamcain/obsidian-calendar-plugin" },
    @{ Name = "Periodic Notes"; Repo = "liamcain/obsidian-periodic-notes" },
    @{ Name = "Advanced Tables";Repo = "tgrosinger/advanced-tables-obsidian" },
    @{ Name = "Icon Folder";    Repo = "FlorianWoelki/obsidian-icon-folder" }
)

if (-not (Test-Path $VaultPath)) {
    Write-Host "错误：找不到仓库路径 $VaultPath" -ForegroundColor Red
    exit 1
}
$pluginsDir = Join-Path $VaultPath ".obsidian\plugins"
New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
Write-Host "目标仓库：$VaultPath" -ForegroundColor Cyan

$installedIds = @()

foreach ($p in $plugins) {
    $base = "https://github.com/$($p.Repo)/releases/latest/download"
    $tmpDir = Join-Path $env:TEMP ("obsplug-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    Write-Host "==> 下载 $($p.Name)  ($($p.Repo))" -ForegroundColor Yellow
    try {
        foreach ($f in @("main.js", "manifest.json", "styles.css")) {
            try {
                Invoke-WebRequest -Uri "$base/$f" -OutFile (Join-Path $tmpDir $f) -UseBasicParsing -TimeoutSec 90
            } catch {
                if ($f -eq "styles.css") { Write-Host "    (该插件无 styles.css，跳过)" }
                else { throw }
            }
        }
        $manifest = Get-Content (Join-Path $tmpDir "manifest.json") -Raw | ConvertFrom-Json
        $pluginDir = Join-Path $pluginsDir $manifest.id
        New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
        foreach ($f in @("main.js", "manifest.json", "styles.css")) {
            $src = Join-Path $tmpDir $f
            if (Test-Path $src) { Copy-Item $src (Join-Path $pluginDir $f) -Force }
        }
        $installedIds += $manifest.id
        Write-Host "    已安装：.obsidian/plugins/$($manifest.id)  v$($manifest.version)" -ForegroundColor Green
    } catch {
        Write-Host "    安装失败：$($_.Exception.Message)" -ForegroundColor Red
    } finally {
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 把新插件写入 community-plugins.json（Obsidian 据此识别"已启用"插件）
$registryPath = Join-Path $VaultPath ".obsidian\community-plugins.json"
$registry = @()
if (Test-Path $registryPath) {
    try { $registry = @(Get-Content $registryPath -Raw | ConvertFrom-Json) } catch { $registry = @() }
}
$changed = $false
foreach ($id in $installedIds) {
    if ($id -notin $registry) { $registry += $id; $changed = $true }
}
if ($changed) {
    $registry | ConvertTo-Json | Set-Content $registryPath -Encoding UTF8
    Write-Host "`n已更新 community-plugins.json：$(($registry -join ', '))" -ForegroundColor Cyan
} else {
    Write-Host "`ncommunity-plugins.json 无需更新（插件已全部登记）"
}

Write-Host "`n完成。请重启 Obsidian 或在命令面板(Ctrl+P)执行 'Reload app without saving' 加载插件。" -ForegroundColor Green
Write-Host "然后到 设置 -> 第三方插件 里确认/配置各插件。" -ForegroundColor Green

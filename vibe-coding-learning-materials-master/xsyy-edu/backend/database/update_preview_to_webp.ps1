# PowerShell 脚本：更新数据库 preview_image 字段为 preview.webp
# 使用方法：在 PowerShell 中运行
# .\backend\database\update_preview_to_webp.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Split-Path -Parent $scriptDir
$projectRoot = Split-Path -Parent $backendDir
$sqlFile = Join-Path $scriptDir "update_preview_to_webp.sql"

Write-Host "=" * 60
Write-Host "更新数据库 preview_image 字段为 preview.webp"
Write-Host "=" * 60
Write-Host ""

# 读取 SQL 文件内容
$sqlContent = Get-Content $sqlFile -Raw -Encoding UTF8

# 执行 SQL（需要先配置数据库连接信息）
Write-Host "请手动执行以下 SQL 语句："
Write-Host ""
Write-Host $sqlContent
Write-Host ""
Write-Host "或者在 MySQL 客户端中执行："
Write-Host "  mysql -u root -p xsyy"
Write-Host "  然后复制粘贴上面的 SQL 语句"
Write-Host ""

# 或者使用 Python 脚本（更简单）
Write-Host "或者运行 Python 脚本（推荐）："
Write-Host "  python backend\database\update_preview_to_webp_simple.py -y"
Write-Host ""


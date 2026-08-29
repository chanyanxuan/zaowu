# 造物工坊 部署包打包脚本:把代码 + CAD 内核 + 3D 预览器 + Docker 配置打成 zaowu-deploy.zip
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Administrator\Desktop\text2cad'
$stage = Join-Path $env:TEMP 'zaowu-stage'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

# 应用代码与配置
Copy-Item "$root\web_app.py","$root\text2cad_proto.py","$root\billing.py","$root\users.py","$root\pay.py","$root\jobstore.py" $stage
Copy-Item "$root\Dockerfile","$root\docker-compose.yml","$root\nginx.conf","$root\start.sh","$root\requirements_server.txt","$root\.env.example","$root\上线清单.md" $stage
Copy-Item "$root\web" "$stage\web" -Recurse

# CAD 内核(cadgen 运行时)
$cadDst = "$stage\text-to-cad\skills\cad"
New-Item -ItemType Directory -Force -Path $cadDst | Out-Null
Copy-Item "$root\text-to-cad\skills\cad\scripts" "$cadDst\scripts" -Recurse

# 3D 预览器(不含备份与 MoveIt2 服务)
Copy-Item 'C:\Users\Administrator\.agents\skills\cad-viewer\scripts\viewer' "$stage\viewer" -Recurse
Remove-Item "$stage\viewer\dist.bak" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$stage\viewer\moveit2_server" -Recurse -Force -ErrorAction SilentlyContinue

$zip = "$root\zaowu-deploy.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zip -Force
Remove-Item $stage -Recurse -Force
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "✅ 打包完成: $zip ($size MB)"

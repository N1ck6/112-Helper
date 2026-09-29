# Установка и запуск тренажёра ДДС-112 на Windows (вызывает start.bat из корня репозитория).
# 1) Docker Desktop установлен и запущен; 2) .env — создать со случайными паролями или дополнить;
# 3) docker compose up; 4) дождаться готовности и открыть АРМ в браузере.
# Повторный запуск безопасен: .env не перезаписывается, данные в БД сохраняются.

# Continue: docker пишет прогресс в stderr, PowerShell 5.1 при Stop счёл бы это ошибкой;
# успех каждой команды проверяется по $LASTEXITCODE
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nОШИБКА: $text" -ForegroundColor Red; exit 1 }

function Test-Docker {
    docker info *> $null
    return $LASTEXITCODE -eq 0
}

Step "Проверка Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker не установлен. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/ и запустите этот файл снова."
}
if (-not (Test-Docker)) {
    $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Write-Host "Docker Desktop не запущен — запускаю и жду (до 3 минут)..."
        Start-Process $desktop
        $deadline = (Get-Date).AddMinutes(3)
        while (-not (Test-Docker) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 5; Write-Host -NoNewline "." }
        Write-Host ""
    }
    if (-not (Test-Docker)) { Fail "Docker не отвечает. Запустите Docker Desktop и повторите." }
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Нет docker compose v2. Обновите Docker Desktop." }
Write-Host "Docker готов."

Step "Файл настроек .env"
# IP этого ПК в локальной сети: по нему софтфоны других рабочих мест получают звук
$ip = ""
try {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop | Sort-Object RouteMetric | Select-Object -First 1
    $ip = (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction Stop | Select-Object -First 1).IPAddress
} catch { $ip = "" }
docker run --rm -v "${Root}:/work" -w /work python:3.12-alpine python deploy/make_env.py --media-ip "$ip"
if ($LASTEXITCODE -ne 0) { Fail "Не удалось создать .env" }

$envValues = @{}
Get-Content (Join-Path $Root ".env") -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*([A-Z_0-9]+)\s*=\s*(.*)$') { $envValues[$Matches[1]] = $Matches[2].Trim() }
}
$port = if ($envValues["FRONTEND_PORT"]) { $envValues["FRONTEND_PORT"] } else { "8080" }
$url = "http://localhost:$port"

Step "Сборка и запуск сервисов (первый раз — 10-30 минут: образы, модели голоса и ИИ)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "docker compose up завершился с ошибкой. Подробности: docker compose logs" }

Step "Ожидание готовности (база данных, ИИ-сервис, стартовые данные)"
$deadline = (Get-Date).AddMinutes(30)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "$url/api/health/ready" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 10
    Write-Host -NoNewline "."
}
Write-Host ""
if (-not $ready) { Fail "Стенд не ответил за 30 минут. Состояние: docker compose ps; журналы: docker compose logs api ml" }

Write-Host "`nТренажёр запущен: $url" -ForegroundColor Green
Write-Host "С других компьютеров класса: http://${ip}:$port"
Write-Host "`nУчётные записи (пароли хранятся в файле .env):"
Write-Host ("  admin            {0}   администратор" -f $envValues["ADMIN_PASSWORD"])
Write-Host ("  teacher          {0}   преподаватель" -f $envValues["TEACHER_PASSWORD"])
Write-Host ("  student, student2 {0}  обучающиеся" -f $envValues["STUDENT_PASSWORD"])
Write-Host ("  Софтфон рабочего места: сервер ${ip}:{0}, логин ws01…ws20, пароль {1}" -f $envValues["EXTERNAL_SIGNALING_PORT"], $envValues["TRAINEE_PASSWORD"])
Write-Host "  Настройка MicroSIP (UDP, логин = номер места при входе в АРМ) — README, раздел «Подключение MicroSIP»"
if ($envValues["COMPOSE_PROFILES"] -match "llm") {
    Write-Host "`nМодель ИИ ($($envValues['LLM_MODEL'])) и голоса при первом запуске докачиваются в фоне;"
    Write-Host "до этого проверка грамотности и рассказы заявителей идут по правилам. Ход: docker compose logs -f ollama-init voice-service"
}
Write-Host "`nОстановить: docker compose stop    Запустить снова: start.bat"
Start-Process $url

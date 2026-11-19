# Scaling benchmark (F1c): throughput and latency with 1, 2, 4, 8 application containers behind Nginx.
#
#   1. docker compose up -d --build ; create an admin ; create an API key WITHOUT quota or IP restriction
#   2. $env:API_KEY = "ecode_..."
#   3. .\stress\run_scaling.ps1                       (optional: -Workload typical|small|a4|pdf|mix  -Users 64  -Seconds 60)
#
# Results: stress/results/scaling_<workload>_app<N>_stats.csv  (one row "Aggregated" per run)
# Run it on the machine(s) you want to size, and keep Locust on ANOTHER machine when possible: on one
# machine the load generator competes with the application for the same CPU cores.
param(
    [string]$Workload = 'typical',
    [int]$Users = 64,
    [int]$Seconds = 60,
    [int[]]$Replicas = @(1, 2, 4, 8),
    [string]$BaseUrl = ''
)
# Default address = Nginx port from .env (HTTP_PORT), like docker-compose.yml
if (-not $BaseUrl) {
    $port = '8080'
    $line = Select-String -Path .env -Pattern '^HTTP_PORT=(\d+)' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($line) { $port = $line.Matches[0].Groups[1].Value }
    $BaseUrl = "http://localhost:$port"
}
# Safety check: the address must answer like OUR platform, otherwise the whole run would hit another program
$health = (curl.exe -s -m 5 "$BaseUrl/health")
if ($health -notmatch '"status"\s*:\s*"ok"') { throw "$BaseUrl/health did not answer like the platform (got: $health). Check the port (HTTP_PORT) or pass -BaseUrl." }
if (-not $env:API_KEY) { throw 'Set $env:API_KEY first (key without quota)' }
$env:WORKLOAD = $Workload
New-Item -ItemType Directory -Force -Path stress/results | Out-Null

foreach ($n in $Replicas) {
    Write-Host "=== $n application container(s) ==="
    docker compose up -d --scale app=$n --no-recreate | Out-Null
    Start-Sleep -Seconds 15            # containers healthy, Nginx has re-resolved the new addresses
    locust -f stress/locustfile.py --headless -u $Users -r $Users -t "${Seconds}s" `
        --host $BaseUrl --csv "stress/results/scaling_${Workload}_app$n" --only-summary
}

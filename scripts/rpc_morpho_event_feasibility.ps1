[CmdletBinding()]
param(
    [string]$RpcUrl = 'https://arb1.arbitrum.io/rpc',
    [string]$GbaProjectId = 'codex-bq-sbx-20260811-002cd5',
    [datetime]$StartUtc = [datetime]'2026-08-17T00:00:00Z',
    [datetime]$EndExclusiveUtc = [datetime]'2026-08-18T00:00:00Z',
    [int]$InitialBlockSpan = 20000,
    [int]$MaximumBlockSpan = 80000,
    [int]$MaximumRetries = 3,
    [int]$StopAfterSuccessfulRanges = 0,
    [string]$RunSuffix = '',
    [string]$GbaReferenceSourcePath = '',
    [switch]$RefreshGba
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$dayLabel = $StartUtc.ToUniversalTime().ToString('yyyy-MM-dd')
if ($RunSuffix -notmatch '^[A-Za-z0-9_-]*$') { throw 'RunSuffix may contain only letters, digits, underscore, and hyphen.' }
$runLabel = $dayLabel + $RunSuffix
$outputRoot = Join-Path $workspaceRoot "data/tmp/rpc_feasibility_$runLabel"
$manifestPath = Join-Path $outputRoot 'manifest.json'
$legacyCheckpointPath = Join-Path $outputRoot 'checkpoint.json'
$shardRoot = Join-Path $outputRoot 'shards'
$gbaReferencePath = Join-Path $outputRoot 'gba_reference.csv'
$gbaStderrPath = Join-Path $outputRoot 'gba_query.stderr.txt'
$errorCheckpointPath = Join-Path $outputRoot 'errors.csv'
$gbaSqlPath = Join-Path $workspaceRoot 'sql/02_rpc_stratified_gba_reference.sql'
$marketCsvPath = Join-Path $workspaceRoot 'data/drip_morpho_markets.csv'
$summaryJsonPath = Join-Path $workspaceRoot "data/morpho_rpc_feasibility_${runLabel}_summary.json"
$summaryCsvPath = Join-Path $workspaceRoot "data/morpho_rpc_feasibility_${runLabel}_summary.csv"
$mismatchCsvPath = Join-Path $workspaceRoot "data/morpho_rpc_feasibility_${runLabel}_mismatches.csv"
$publishedRangesPath = Join-Path $workspaceRoot "data/morpho_rpc_feasibility_${runLabel}_ranges.csv"
$publishedErrorsPath = Join-Path $workspaceRoot "data/morpho_rpc_feasibility_${runLabel}_errors.csv"
$resumeTestPath = Join-Path $workspaceRoot "data/morpho_rpc_feasibility_${runLabel}_resume_test.json"

$morphoAddress = '0x6c247b1f6182318877311737bac0844baa518f5e'
$eventHashes = @(
    '0xedf8870433c83823eb071d3df1caa8d008f12f6440918c20d75a3602cda30fe0',
    '0xa56fc0ad5702ec05ce63666221f796fb62437c32db1aa1aa075fc6484cf58fbf',
    '0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43',
    '0x52acb05cebbd3cd39715469f22afbf5a17496295ef3bc9bb5944056c63ccaa09',
    '0xa3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184',
    '0xe80ebd7cc9223d7382aab2e0d1d6155c65651f83d53c8b9b06901d167e321142',
    '0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41',
    '0x9d9bd501d0657d7dfe415f779a620a62b78bc508ddc0891fbbd8b7ac0f8fce87'
)
$marketIds = @((Import-Csv -LiteralPath $marketCsvPath).market_id | ForEach-Object { $_.ToLowerInvariant() })
if ($marketIds.Count -ne 45) {
    throw "Expected 45 eligible market IDs, found $($marketIds.Count)."
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $shardRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $manifestPath) -and (Test-Path -LiteralPath $legacyCheckpointPath)) {
    throw "This run label contains a legacy whole-file checkpoint. Use a new RunSuffix; automatic migration is intentionally disabled."
}
if (-not (Test-Path -LiteralPath $manifestPath)) {
    $orphanShardFiles = @(Get-ChildItem -LiteralPath $shardRoot -File | Where-Object { $_.Name -like '*.jsonl' -or $_.Name -like '*.part' })
    if ($orphanShardFiles.Count -gt 0) {
        throw "Found shard files without a manifest; refusing to continue until reviewed: $($orphanShardFiles.Name -join ', ')"
    }
}

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$metrics = [ordered]@{
    rpc_attempts_total = 0
    rpc_successful_responses = 0
    rpc_error_attempts = 0
    rpc_retries = 0
    rpc_response_bytes_total = [int64]0
    eth_getLogs_attempts = 0
    eth_getLogs_successful_responses = 0
    eth_getLogs_response_bytes = [int64]0
    successful_block_ranges = 0
    adaptive_range_reductions = 0
    adaptive_range_expansions = 0
    block_lookup_attempts = 0
}
$requestId = 0
$errorRecords = [System.Collections.Generic.List[object]]::new()
$rangeRecords = [System.Collections.Generic.List[object]]::new()
$rpcLogs = [System.Collections.Generic.List[object]]::new()
$blockTimestampCache = @{}
$runWatch = [System.Diagnostics.Stopwatch]::StartNew()
$executionStartedUtc = [datetime]::UtcNow

function Add-Metric {
    param([string]$Name, [int64]$Amount = 1)
    $script:metrics[$Name] = [int64]$script:metrics[$Name] + $Amount
}

function Write-AtomicText {
    param([string]$Path, [string]$Text)
    $resolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $Path))
    $resolvedWorkspace = [System.IO.Path]::GetFullPath($script:workspaceRoot)
    if (-not $resolvedParent.StartsWith($resolvedWorkspace, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside workspace: $Path"
    }
    $temporaryPath = "$Path.part"
    [System.IO.File]::WriteAllText($temporaryPath, $Text, $script:utf8NoBom)
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Write-ObjectsCsv {
    param([string]$Path, [object[]]$Rows, [string[]]$EmptyHeader)
    if ($Rows.Count -gt 0) {
        $text = ($Rows | ConvertTo-Csv -NoTypeInformation) -join [Environment]::NewLine
    } else {
        $text = ($EmptyHeader | ForEach-Object { '"' + $_.Replace('"', '""') + '"' }) -join ','
    }
    Write-AtomicText -Path $Path -Text ($text + [Environment]::NewLine)
}

function Save-Manifest {
    param(
        [int64]$StartBlock,
        [int64]$EndBlockExclusive,
        [int64]$NextBlock,
        [int]$CurrentSpan,
        [bool]$Complete
    )
    Write-ObjectsCsv -Path $script:errorCheckpointPath -Rows $script:errorRecords.ToArray() -EmptyHeader @(
        'occurred_at_utc','method','attempt','message'
    )
    $manifest = [ordered]@{
        version = 2
        storage = 'append-only immutable range shards'
        population = 'Morpho contract x 8 critical event hashes x 45 DRIP-eligible market IDs'
        start_utc = $script:StartUtc.ToUniversalTime().ToString('o')
        end_exclusive_utc = $script:EndExclusiveUtc.ToUniversalTime().ToString('o')
        start_block = $StartBlock
        end_block_exclusive = $EndBlockExclusive
        next_block = $NextBlock
        current_span = $CurrentSpan
        status = if ($Complete) { 'complete' } else { 'in_progress' }
        complete = $Complete
        verified_shard_count = $script:rangeRecords.Count
        row_count = $script:rpcLogs.Count
        shards = @($script:rangeRecords.ToArray())
        metrics = $script:metrics
        updated_at_utc = [datetime]::UtcNow.ToString('o')
    }
    Write-AtomicText -Path $script:manifestPath -Text ($manifest | ConvertTo-Json -Depth 12)
}

function Get-Sha256Lower {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Convert-RangeLogsToRows {
    param([object[]]$RangeLogs)
    return @($RangeLogs | ForEach-Object {
        [pscustomobject]@{
            block_number = Convert-FromHexQuantity ([string]$_.blockNumber)
            transaction_hash = ([string]$_.transactionHash).ToLowerInvariant()
            transaction_index = Convert-FromHexQuantity ([string]$_.transactionIndex)
            log_index = Convert-FromHexQuantity ([string]$_.logIndex)
            address = ([string]$_.address).ToLowerInvariant()
            topics_json = Normalize-TopicsJson @($_.topics)
            data = ([string]$_.data).ToLowerInvariant()
            removed = [bool]$_.removed
        }
    })
}

function Read-AndValidateShard {
    param(
        [object]$Entry,
        [System.Collections.Generic.HashSet[string]]$SeenKeys
    )
    if ([string]$Entry.status -cne 'verified') { throw "Shard $($Entry.range_id) is not verified in manifest." }
    $fileName = [string]$Entry.file
    if ([System.IO.Path]::GetFileName($fileName) -cne $fileName) { throw "Unsafe shard path in manifest: $fileName" }
    $path = Join-Path $script:shardRoot $fileName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing manifest shard: $path" }
    $actualChecksum = Get-Sha256Lower -Path $path
    if ($actualChecksum -cne ([string]$Entry.checksum_sha256).ToLowerInvariant()) {
        throw "Checksum mismatch for shard $fileName."
    }
    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($line in @(Get-Content -LiteralPath $path)) {
        if ([string]::IsNullOrWhiteSpace([string]$line)) { continue }
        $row = [string]$line | ConvertFrom-Json -Depth 20
        $block = [int64]$row.block_number
        if ($block -lt [int64]$Entry.from_block -or $block -ge [int64]$Entry.to_block_exclusive) {
            throw "Row block $block falls outside shard range [$($Entry.from_block), $($Entry.to_block_exclusive))."
        }
        $key = Get-Key $row
        if (-not $SeenKeys.Add($key)) { throw "Duplicate RPC event key while verifying shards: $key" }
        $rows.Add($row)
    }
    if ($rows.Count -ne [int64]$Entry.row_count) {
        throw "Row-count mismatch for shard ${fileName}: manifest=$($Entry.row_count), actual=$($rows.Count)."
    }
    return @($rows.ToArray())
}

function Write-ImmutableRangeShard {
    param(
        [int]$RangeId,
        [int64]$FromBlock,
        [int64]$ToBlockExclusive,
        [object[]]$Rows
    )
    $fileName = ('range_{0:d6}_{1}_{2}.jsonl' -f $RangeId, $FromBlock, $ToBlockExclusive)
    $finalPath = Join-Path $script:shardRoot $fileName
    $partPath = "$finalPath.part"
    if ((Test-Path -LiteralPath $finalPath) -or (Test-Path -LiteralPath $partPath)) {
        throw "Refusing to overwrite an existing immutable shard or .part: $fileName"
    }
    $payload = if ($Rows.Count -eq 0) { '' } else {
        (($Rows | ForEach-Object { $_ | ConvertTo-Json -Depth 12 -Compress }) -join [Environment]::NewLine) + [Environment]::NewLine
    }
    [System.IO.File]::WriteAllText($partPath, $payload, $script:utf8NoBom)
    $partChecksum = Get-Sha256Lower -Path $partPath
    Move-Item -LiteralPath $partPath -Destination $finalPath
    $finalChecksum = Get-Sha256Lower -Path $finalPath
    if ($partChecksum -cne $finalChecksum) { throw "Shard checksum changed during atomic rename: $fileName" }
    return [pscustomobject]@{
        file = $fileName
        checksum_sha256 = $finalChecksum
        file_bytes = (Get-Item -LiteralPath $finalPath).Length
    }
}

function Convert-ToHexQuantity {
    param([int64]$Value)
    return ('0x{0:x}' -f $Value)
}

function Convert-FromHexQuantity {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or -not $Value.StartsWith('0x')) {
        throw "Invalid hex quantity: $Value"
    }
    return [Convert]::ToInt64($Value.Substring(2), 16)
}

function Invoke-RpcRequest {
    param([string]$Method, [object[]]$Parameters)
    $lastException = $null
    for ($attempt = 1; $attempt -le ($script:MaximumRetries + 1); $attempt++) {
        $script:requestId++
        Add-Metric -Name 'rpc_attempts_total'
        if ($Method -eq 'eth_getLogs') { Add-Metric -Name 'eth_getLogs_attempts' }
        if ($Method -eq 'eth_getBlockByNumber') { Add-Metric -Name 'block_lookup_attempts' }
        $body = [ordered]@{
            jsonrpc = '2.0'
            id = $script:requestId
            method = $Method
            params = $Parameters
        } | ConvertTo-Json -Depth 20 -Compress
        $callWatch = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $script:RpcUrl -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 60
            $content = [string]$response.Content
            $responseBytes = [System.Text.Encoding]::UTF8.GetByteCount($content)
            Add-Metric -Name 'rpc_response_bytes_total' -Amount $responseBytes
            if ($Method -eq 'eth_getLogs') { Add-Metric -Name 'eth_getLogs_response_bytes' -Amount $responseBytes }
            $json = $content | ConvertFrom-Json -Depth 30
            $errorProperty = $json.PSObject.Properties['error']
            if ($null -ne $errorProperty -and $null -ne $errorProperty.Value) {
                $rpcError = $errorProperty.Value
                $codeProperty = $rpcError.PSObject.Properties['code']
                $code = if ($null -ne $codeProperty) { $codeProperty.Value } else { 'unknown' }
                throw "RPC error $code`: $($rpcError.message)"
            }
            Add-Metric -Name 'rpc_successful_responses'
            if ($Method -eq 'eth_getLogs') { Add-Metric -Name 'eth_getLogs_successful_responses' }
            $callWatch.Stop()
            return [pscustomobject]@{
                result = $json.result
                response_bytes = $responseBytes
                attempts = $attempt
                elapsed_ms = $callWatch.ElapsedMilliseconds
            }
        } catch {
            $callWatch.Stop()
            $lastException = $_.Exception
            Add-Metric -Name 'rpc_error_attempts'
            $script:errorRecords.Add([pscustomobject]@{
                occurred_at_utc = [datetime]::UtcNow.ToString('o')
                method = $Method
                attempt = $attempt
                message = $lastException.Message
            })
            if ($attempt -le $script:MaximumRetries) {
                Add-Metric -Name 'rpc_retries'
                Start-Sleep -Seconds ([math]::Min(8, [math]::Pow(2, $attempt - 1)))
            }
        }
    }
    throw $lastException
}

function Get-BlockTimestampUnix {
    param([int64]$BlockNumber)
    $cacheKey = $BlockNumber.ToString()
    if ($script:blockTimestampCache.ContainsKey($cacheKey)) {
        return [int64]$script:blockTimestampCache[$cacheKey]
    }
    $envelope = Invoke-RpcRequest -Method 'eth_getBlockByNumber' -Parameters @((Convert-ToHexQuantity $BlockNumber), $false)
    if ($null -eq $envelope.result) { throw "Block $BlockNumber was not returned by RPC." }
    $timestamp = Convert-FromHexQuantity ([string]$envelope.result.timestamp)
    $script:blockTimestampCache[$cacheKey] = $timestamp
    return $timestamp
}

function Find-FirstBlockAtOrAfter {
    param([int64]$TargetUnix, [int64]$LatestBlock)
    if ((Get-BlockTimestampUnix $LatestBlock) -lt $TargetUnix) {
        throw "Target timestamp is after the latest RPC block."
    }
    [int64]$low = 0
    [int64]$high = $LatestBlock
    while ($low -lt $high) {
        [int64]$mid = $low + [math]::Floor(($high - $low) / 2)
        if ((Get-BlockTimestampUnix $mid) -ge $TargetUnix) {
            $high = $mid
        } else {
            $low = $mid + 1
        }
    }
    return $low
}

function Normalize-TopicsJson {
    param([object[]]$Topics)
    $normalized = @($Topics | ForEach-Object { ([string]$_).ToLowerInvariant() })
    return ($normalized | ConvertTo-Json -Compress)
}

function Get-Key {
    param($Row)
    return "$($Row.block_number)|$(([string]$Row.transaction_hash).ToLowerInvariant())|$($Row.log_index)"
}

function Get-GbaReference {
    $gbaHeader = '"block_timestamp_utc","block_number","transaction_hash","transaction_index","log_index","address","topics_json","data","removed"' + [Environment]::NewLine
    if ((Test-Path -LiteralPath $script:gbaReferencePath) -and -not $script:RefreshGba) {
        if ((Get-Item -LiteralPath $script:gbaReferencePath).Length -le 2) {
            Write-AtomicText -Path $script:gbaReferencePath -Text $gbaHeader
        }
        return @(Import-Csv -LiteralPath $script:gbaReferencePath)
    }
    if (-not [string]::IsNullOrWhiteSpace($script:GbaReferenceSourcePath)) {
        $sourcePath = [System.IO.Path]::GetFullPath($script:GbaReferenceSourcePath)
        $resolvedWorkspace = [System.IO.Path]::GetFullPath($script:workspaceRoot)
        if (-not $sourcePath.StartsWith($resolvedWorkspace, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "GbaReferenceSourcePath must be inside the workspace: $sourcePath"
        }
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "GBA reference source does not exist: $sourcePath"
        }
        $csvText = [System.IO.File]::ReadAllText($sourcePath)
        Write-AtomicText -Path $script:gbaReferencePath -Text $csvText
        return @($csvText | ConvertFrom-Csv)
    }
    $sqlText = Get-Content -Raw -LiteralPath $script:gbaSqlPath
    $sqlText = $sqlText.Replace('__START_UTC__', $script:StartUtc.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss+00'))
    $sqlText = $sqlText.Replace('__END_EXCLUSIVE_UTC__', $script:EndExclusiveUtc.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss+00'))
    $compactSql = [regex]::Replace($sqlText, '(?s)/\*.*?\*/', ' ')
    $compactSql = [regex]::Replace($compactSql, '\s+', ' ').Trim()
    $queryWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $output = & bq query "--project_id=$script:GbaProjectId" '--location=US' '--use_legacy_sql=false' '--format=csv' '--max_rows=100000' '--quiet' $compactSql 2> $script:gbaStderrPath
    $exitCode = $LASTEXITCODE
    $queryWatch.Stop()
    if ($exitCode -ne 0) {
        $stderr = if (Test-Path -LiteralPath $script:gbaStderrPath) { Get-Content -Raw -LiteralPath $script:gbaStderrPath } else { '' }
        throw "GBA reference query failed with exit code $exitCode. $stderr"
    }
    $outputLines = @($output | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    $csvText = if ($outputLines.Count -eq 0) { $gbaHeader } else {
        ($outputLines -join [Environment]::NewLine) + [Environment]::NewLine
    }
    Write-AtomicText -Path $script:gbaReferencePath -Text $csvText
    $script:gbaQueryElapsedSeconds = [math]::Round($queryWatch.Elapsed.TotalSeconds, 3)
    return @($csvText | ConvertFrom-Csv)
}

$gbaQueryElapsedSeconds = [double]0
$gbaRows = @(Get-GbaReference)
Write-Host "GBA reference ready: $($gbaRows.Count) rows."

[int64]$startBlock = 0
[int64]$endBlockExclusive = 0
[int64]$nextBlock = 0
[int]$currentSpan = $InitialBlockSpan
$checkpointWasLoaded = $false
$checkpointComplete = $false
$manifestWasCompleteAtLoad = $false
$resumeStartBlock = [int64]0
$resumeLoadedShardCount = 0
$resumeLoadedRowCount = 0
$resumeLoadedFingerprints = @()
$chainId = 42161
if (Test-Path -LiteralPath $manifestPath) {
    $partFiles = @(Get-ChildItem -LiteralPath $shardRoot -Filter '*.part' -File)
    if ($partFiles.Count -gt 0) {
        throw "Found orphan .part shard(s); refusing resume until reviewed: $($partFiles.Name -join ', ')"
    }
    $saved = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -Depth 20
    if ([int]$saved.version -ne 2) { throw "Unsupported manifest version $($saved.version)." }
    if ([datetime]$saved.start_utc -ne $StartUtc.ToUniversalTime() -or [datetime]$saved.end_exclusive_utc -ne $EndExclusiveUtc.ToUniversalTime()) {
        throw 'Existing manifest has different time boundaries.'
    }
    $checkpointWasLoaded = $true
    $checkpointComplete = [bool]$saved.complete
    $manifestWasCompleteAtLoad = $checkpointComplete
    $startBlock = [int64]$saved.start_block
    $endBlockExclusive = [int64]$saved.end_block_exclusive
    $nextBlock = [int64]$saved.next_block
    $currentSpan = [int]$saved.current_span
    foreach ($property in $saved.metrics.PSObject.Properties) {
        if ($metrics.Contains($property.Name)) { $metrics[$property.Name] = [int64]$property.Value }
    }
    $seenKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $manifestFiles = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    [int64]$expectedFromBlock = $startBlock
    [int]$expectedRangeId = 1
    foreach ($entry in @($saved.shards)) {
        if ([int]$entry.range_id -ne $expectedRangeId) { throw "Manifest range_id sequence breaks at $expectedRangeId." }
        if ([int64]$entry.from_block -ne $expectedFromBlock) {
            throw "Manifest gap or overlap before shard ${expectedRangeId}: expected from_block $expectedFromBlock, found $($entry.from_block)."
        }
        if ([int64]$entry.to_block_exclusive -le [int64]$entry.from_block -or [int64]$entry.to_block_exclusive -gt $endBlockExclusive) {
            throw "Invalid block boundaries in shard $expectedRangeId."
        }
        if (-not $manifestFiles.Add([string]$entry.file)) { throw "Duplicate shard filename in manifest: $($entry.file)" }
        foreach ($row in @(Read-AndValidateShard -Entry $entry -SeenKeys $seenKeys)) { $rpcLogs.Add($row) }
        $rangeRecords.Add($entry)
        $expectedFromBlock = [int64]$entry.to_block_exclusive
        $expectedRangeId++
    }
    if ($expectedFromBlock -ne $nextBlock) { throw "Manifest next_block does not follow its last verified shard." }
    if ($rangeRecords.Count -ne [int]$saved.verified_shard_count) { throw "Manifest verified_shard_count does not match its shard entries." }
    if ($rpcLogs.Count -ne [int64]$saved.row_count) { throw "Manifest total row_count does not match verified shards." }
    if ($checkpointComplete -and $nextBlock -ne $endBlockExclusive) { throw "Complete manifest does not cover the full block interval." }
    if ($checkpointComplete -and [string]$saved.status -cne 'complete') { throw "Complete manifest must have complete status." }
    if (-not $checkpointComplete -and [string]$saved.status -cne 'in_progress') { throw "Incomplete manifest must have in_progress status." }
    $orphanFinalShards = @(Get-ChildItem -LiteralPath $shardRoot -Filter '*.jsonl' -File | Where-Object { -not $manifestFiles.Contains($_.Name) })
    if ($orphanFinalShards.Count -gt 0) {
        throw "Found immutable shard(s) not referenced by manifest; refusing resume: $($orphanFinalShards.Name -join ', ')"
    }
    if (Test-Path -LiteralPath $errorCheckpointPath) {
        foreach ($row in @(Import-Csv -LiteralPath $errorCheckpointPath)) { $errorRecords.Add($row) }
    }
    $resumeStartBlock = $nextBlock
    $resumeLoadedShardCount = $rangeRecords.Count
    $resumeLoadedRowCount = $rpcLogs.Count
    $resumeLoadedFingerprints = @($rangeRecords.ToArray() | ForEach-Object {
        [pscustomobject]@{ file = [string]$_.file; checksum_sha256 = [string]$_.checksum_sha256 }
    })
    Write-Host "Verified manifest loaded: complete=$checkpointComplete, shards=$($rangeRecords.Count), logs=$($rpcLogs.Count), next block=$nextBlock."
} else {
    $chainEnvelope = Invoke-RpcRequest -Method 'eth_chainId' -Parameters @()
    $chainId = Convert-FromHexQuantity ([string]$chainEnvelope.result)
    if ($chainId -ne 42161) { throw "Unexpected chain ID $chainId." }
    $latestEnvelope = Invoke-RpcRequest -Method 'eth_blockNumber' -Parameters @()
    $latestBlock = Convert-FromHexQuantity ([string]$latestEnvelope.result)
    $startUnix = ([DateTimeOffset]$StartUtc.ToUniversalTime()).ToUnixTimeSeconds()
    $endUnix = ([DateTimeOffset]$EndExclusiveUtc.ToUniversalTime()).ToUnixTimeSeconds()
    $startBlock = Find-FirstBlockAtOrAfter -TargetUnix $startUnix -LatestBlock $latestBlock
    $endBlockExclusive = Find-FirstBlockAtOrAfter -TargetUnix $endUnix -LatestBlock $latestBlock
    $nextBlock = $startBlock
    $resumeStartBlock = $startBlock
}
Write-Host "UTC block interval: [$startBlock, $endBlockExclusive)."

$collectionWatch = [System.Diagnostics.Stopwatch]::StartNew()
while ($nextBlock -lt $endBlockExclusive) {
    [int64]$toBlock = [math]::Min($endBlockExclusive - 1, $nextBlock + $currentSpan - 1)
    $filter = [ordered]@{
        fromBlock = Convert-ToHexQuantity $nextBlock
        toBlock = Convert-ToHexQuantity $toBlock
        address = $morphoAddress
        topics = @($eventHashes, $marketIds)
    }
    try {
        $envelope = Invoke-RpcRequest -Method 'eth_getLogs' -Parameters @($filter)
    } catch {
        if ($currentSpan -le 1) {
            Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
            throw
        }
        $currentSpan = [math]::Max(1, [math]::Floor($currentSpan / 2))
        Add-Metric -Name 'adaptive_range_reductions'
        Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
        continue
    }

    $rangeLogs = @($envelope.result)
    $rangeRows = @(Convert-RangeLogsToRows -RangeLogs $rangeLogs)

    $nextSpan = $currentSpan
    if ($rangeLogs.Count -lt 150 -and $currentSpan -lt $MaximumBlockSpan) {
        $nextSpan = [math]::Min($MaximumBlockSpan, $currentSpan * 2)
        if ($nextSpan -ne $currentSpan) { Add-Metric -Name 'adaptive_range_expansions' }
    } elseif ($rangeLogs.Count -gt 1000 -and $currentSpan -gt 1) {
        $nextSpan = [math]::Max(1, [math]::Floor($currentSpan / 2))
        if ($nextSpan -ne $currentSpan) { Add-Metric -Name 'adaptive_range_reductions' }
    }
    Add-Metric -Name 'successful_block_ranges'
    $rangeId = $rangeRecords.Count + 1
    $shard = Write-ImmutableRangeShard -RangeId $rangeId -FromBlock $nextBlock -ToBlockExclusive ($toBlock + 1) -Rows $rangeRows
    $rangeRecord = [pscustomobject]@{
        range_id = $rangeId
        status = 'verified'
        from_block = $nextBlock
        to_block = $toBlock
        to_block_exclusive = $toBlock + 1
        block_count = $toBlock - $nextBlock + 1
        row_count = $rangeRows.Count
        log_count = $rangeRows.Count
        file = $shard.file
        checksum_algorithm = 'SHA256'
        checksum_sha256 = $shard.checksum_sha256
        file_bytes = $shard.file_bytes
        attempts = $envelope.attempts
        elapsed_ms = $envelope.elapsed_ms
        response_bytes = $envelope.response_bytes
        next_span = $nextSpan
        completed_at_utc = [datetime]::UtcNow.ToString('o')
    }
    $verificationKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($existingRow in $rpcLogs.ToArray()) { [void]$verificationKeys.Add((Get-Key $existingRow)) }
    foreach ($verifiedRow in @(Read-AndValidateShard -Entry $rangeRecord -SeenKeys $verificationKeys)) { $rpcLogs.Add($verifiedRow) }
    $rangeRecords.Add($rangeRecord)
    Write-Host "Range $($rangeRecords.Count): [$nextBlock, $($toBlock + 1)) -> $($rangeLogs.Count) logs; next span $nextSpan."
    $nextBlock = $toBlock + 1
    $currentSpan = $nextSpan
    Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
    if ($StopAfterSuccessfulRanges -gt 0 -and $rangeRecords.Count -ge $StopAfterSuccessfulRanges) {
        $partialKeys = @($rpcLogs.ToArray() | ForEach-Object { Get-Key $_ })
        $resumeEvidence = [ordered]@{
            test = 'intentional stop after completed range'
            day = $dayLabel
            run_label = $runLabel
            stop_after_successful_ranges = $StopAfterSuccessfulRanges
            completed_ranges = $rangeRecords.Count
            checkpoint_log_rows = $rpcLogs.Count
            checkpoint_unique_keys = @($partialKeys | Sort-Object -Unique).Count
            checkpoint_duplicate_rows = $partialKeys.Count - @($partialKeys | Sort-Object -Unique).Count
            next_block = $nextBlock
            end_block_exclusive = $endBlockExclusive
            checkpoint_complete = $false
            manifest_path = 'data/tmp/' + (Split-Path -Leaf $outputRoot) + '/manifest.json'
            completed_shards = @($rangeRecords.ToArray() | ForEach-Object {
                [pscustomobject]@{
                    range_id = [int]$_.range_id
                    from_block = [int64]$_.from_block
                    to_block_exclusive = [int64]$_.to_block_exclusive
                    row_count = [int64]$_.row_count
                    file = [string]$_.file
                    checksum_sha256 = [string]$_.checksum_sha256
                    status = [string]$_.status
                }
            })
            stopped_at_utc = [datetime]::UtcNow.ToString('o')
        }
        Write-AtomicText -Path $resumeTestPath -Text ($resumeEvidence | ConvertTo-Json -Depth 8)
        Write-Host "Intentional resume-test stop after $($rangeRecords.Count) completed range(s); next block $nextBlock."
        exit 20
    }
}
$collectionWatch.Stop()
Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $true

$normalizedGba = @($gbaRows | ForEach-Object {
    $topics = @($_.topics_json | ConvertFrom-Json)
    [pscustomobject]@{
        block_number = [int64]$_.block_number
        transaction_hash = ([string]$_.transaction_hash).ToLowerInvariant()
        transaction_index = [int64]$_.transaction_index
        log_index = [int64]$_.log_index
        address = ([string]$_.address).ToLowerInvariant()
        topics_json = Normalize-TopicsJson $topics
        data = ([string]$_.data).ToLowerInvariant()
        removed = ([string]$_.removed).ToLowerInvariant() -eq 'true'
    }
})

$rpcGroups = @($rpcLogs.ToArray() | Group-Object { Get-Key $_ })
$gbaGroups = @($normalizedGba | Group-Object { Get-Key $_ })
$rpcDuplicateGroups = @($rpcGroups | Where-Object Count -gt 1)
$gbaDuplicateGroups = @($gbaGroups | Where-Object Count -gt 1)
$rpcByKey = @{}
foreach ($group in $rpcGroups) { $rpcByKey[$group.Name] = $group.Group[0] }
$gbaByKey = @{}
foreach ($group in $gbaGroups) { $gbaByKey[$group.Name] = $group.Group[0] }

$mismatches = [System.Collections.Generic.List[object]]::new()
foreach ($key in $gbaByKey.Keys) {
    if (-not $rpcByKey.ContainsKey($key)) {
        $row = $gbaByKey[$key]
        $mismatches.Add([pscustomobject]@{ category='missing_in_rpc'; key=$key; rpc_topics=''; gba_topics=$row.topics_json; rpc_data=''; gba_data=$row.data })
        continue
    }
    $rpcRow = $rpcByKey[$key]
    $gbaRow = $gbaByKey[$key]
    if ($rpcRow.topics_json -cne $gbaRow.topics_json) {
        $mismatches.Add([pscustomobject]@{ category='topics_mismatch'; key=$key; rpc_topics=$rpcRow.topics_json; gba_topics=$gbaRow.topics_json; rpc_data=$rpcRow.data; gba_data=$gbaRow.data })
    }
    if ($rpcRow.data -cne $gbaRow.data) {
        $mismatches.Add([pscustomobject]@{ category='data_mismatch'; key=$key; rpc_topics=$rpcRow.topics_json; gba_topics=$gbaRow.topics_json; rpc_data=$rpcRow.data; gba_data=$gbaRow.data })
    }
}
foreach ($key in $rpcByKey.Keys) {
    if (-not $gbaByKey.ContainsKey($key)) {
        $row = $rpcByKey[$key]
        $mismatches.Add([pscustomobject]@{ category='extra_in_rpc'; key=$key; rpc_topics=$row.topics_json; gba_topics=''; rpc_data=$row.data; gba_data='' })
    }
}

$missingCount = @($mismatches | Where-Object category -eq 'missing_in_rpc').Count
$extraCount = @($mismatches | Where-Object category -eq 'extra_in_rpc').Count
$topicsMismatchCount = @($mismatches | Where-Object category -eq 'topics_mismatch').Count
$dataMismatchCount = @($mismatches | Where-Object category -eq 'data_mismatch').Count
$rpcDuplicateRowsBeyondFirst = if ($rpcDuplicateGroups.Count -eq 0) { 0 } else {
    [int64](($rpcDuplicateGroups | Measure-Object -Property Count -Sum).Sum) - $rpcDuplicateGroups.Count
}
$gbaDuplicateRowsBeyondFirst = if ($gbaDuplicateGroups.Count -eq 0) { 0 } else {
    [int64](($gbaDuplicateGroups | Measure-Object -Property Count -Sum).Sum) - $gbaDuplicateGroups.Count
}
$successfulGetLogsElapsedMs = if ($rangeRecords.Count -eq 0) { 0 } else {
    [int64](($rangeRecords | Measure-Object -Property elapsed_ms -Sum).Sum)
}
$comparisonPass = (
    $rpcLogs.Count -eq $normalizedGba.Count -and
    $rpcDuplicateGroups.Count -eq 0 -and
    $gbaDuplicateGroups.Count -eq 0 -and
    $missingCount -eq 0 -and
    $extraCount -eq 0 -and
    $topicsMismatchCount -eq 0 -and
    $dataMismatchCount -eq 0
)

$manifestGapCount = 0
$manifestOverlapCount = 0
[int64]$manifestExpectedBlock = $startBlock
foreach ($entry in $rangeRecords.ToArray()) {
    $entryFrom = [int64]$entry.from_block
    if ($entryFrom -gt $manifestExpectedBlock) { $manifestGapCount++ }
    if ($entryFrom -lt $manifestExpectedBlock) { $manifestOverlapCount++ }
    $manifestExpectedBlock = [int64]$entry.to_block_exclusive
}
if ($manifestExpectedBlock -lt $endBlockExclusive) { $manifestGapCount++ }
if ($manifestExpectedBlock -gt $endBlockExclusive) { $manifestOverlapCount++ }
$partFilesRemaining = @(Get-ChildItem -LiteralPath $shardRoot -Filter '*.part' -File).Count
$completedRangesRefetched = 0
if ($checkpointWasLoaded) {
    foreach ($entry in @($rangeRecords.ToArray() | Select-Object -Skip $resumeLoadedShardCount)) {
        if ([int64]$entry.from_block -lt $resumeStartBlock) { $completedRangesRefetched++ }
    }
}
$resumeLoadedShardsPreserved = $true
for ($index = 0; $index -lt $resumeLoadedFingerprints.Count; $index++) {
    $currentEntry = $rangeRecords[$index]
    if ([string]$currentEntry.file -cne [string]$resumeLoadedFingerprints[$index].file -or
        [string]$currentEntry.checksum_sha256 -cne [string]$resumeLoadedFingerprints[$index].checksum_sha256) {
        $resumeLoadedShardsPreserved = $false
        break
    }
}
$manifestIntegrityPass = (
    $manifestGapCount -eq 0 -and
    $manifestOverlapCount -eq 0 -and
    $partFilesRemaining -eq 0 -and
    $completedRangesRefetched -eq 0 -and
    $resumeLoadedShardsPreserved
)
$comparisonPass = $comparisonPass -and $manifestIntegrityPass

Write-ObjectsCsv -Path $mismatchCsvPath -Rows $mismatches.ToArray() -EmptyHeader @('category','key','rpc_topics','gba_topics','rpc_data','gba_data')
Write-ObjectsCsv -Path $publishedRangesPath -Rows $rangeRecords.ToArray() -EmptyHeader @('range_id','status','from_block','to_block','to_block_exclusive','block_count','row_count','log_count','file','checksum_algorithm','checksum_sha256','file_bytes','attempts','elapsed_ms','response_bytes','next_span','completed_at_utc')
Write-ObjectsCsv -Path $publishedErrorsPath -Rows $errorRecords.ToArray() -EmptyHeader @('occurred_at_utc','method','attempt','message')

$executionEndedUtc = [datetime]::UtcNow
$runWatch.Stop()
$resumeEvidenceRaw = if (Test-Path -LiteralPath $resumeTestPath) {
    Get-Content -Raw -LiteralPath $resumeTestPath | ConvertFrom-Json -Depth 20
} else { $null }
$resumeStopEvidence = if ($null -ne $resumeEvidenceRaw -and $null -ne $resumeEvidenceRaw.PSObject.Properties['intentional_stop']) {
    $resumeEvidenceRaw.intentional_stop
} else { $resumeEvidenceRaw }
if ($null -ne $resumeStopEvidence -and $checkpointWasLoaded -and -not $manifestWasCompleteAtLoad) {
    $resumeEvidenceDocument = [ordered]@{
        test = 'intentional stop and append-only manifest resume'
        run_label = $runLabel
        intentional_stop = $resumeStopEvidence
        resume = [ordered]@{
            manifest_verified_before_rpc = $true
            resumed_from_block = $resumeStartBlock
            verified_shards_loaded = $resumeLoadedShardCount
            verified_rows_loaded = $resumeLoadedRowCount
            completed_ranges_refetched = $completedRangesRefetched
            loaded_shards_preserved = $resumeLoadedShardsPreserved
            final_verified_shards = $rangeRecords.Count
            final_rows = $rpcLogs.Count
            manifest_gap_count = $manifestGapCount
            manifest_overlap_count = $manifestOverlapCount
            duplicate_key_groups = $rpcDuplicateGroups.Count
            part_files_remaining = $partFilesRemaining
            comparison_pass = $comparisonPass
            completed_at_utc = $executionEndedUtc.ToString('o')
        }
    }
    Write-AtomicText -Path $resumeTestPath -Text ($resumeEvidenceDocument | ConvertTo-Json -Depth 20)
}
$resumeEvidenceFinal = if (Test-Path -LiteralPath $resumeTestPath) {
    Get-Content -Raw -LiteralPath $resumeTestPath | ConvertFrom-Json -Depth 20
} else { $null }
$resumeCheckpointEvidence = if ($null -ne $resumeEvidenceFinal -and $null -ne $resumeEvidenceFinal.PSObject.Properties['intentional_stop']) {
    $resumeEvidenceFinal.intentional_stop
} else { $resumeEvidenceFinal }
$shardFileBytes = if ($rangeRecords.Count -eq 0) { [int64]0 } else {
    [int64](($rangeRecords.ToArray() | Measure-Object -Property file_bytes -Sum).Sum)
}
$summary = [ordered]@{
    test = 'Phase 2 append-only range-shard bounded resume feasibility'
    run_label = $runLabel
    population = 'Official Morpho contract x 8 critical event hashes x 45 DRIP-eligible market IDs'
    rpc_url = $RpcUrl
    chain_id = $chainId
    start_utc = $StartUtc.ToUniversalTime().ToString('o')
    end_exclusive_utc = $EndExclusiveUtc.ToUniversalTime().ToString('o')
    start_block = $startBlock
    end_block_exclusive = $endBlockExclusive
    block_count = $endBlockExclusive - $startBlock
    gba_rows = $normalizedGba.Count
    rpc_rows = $rpcLogs.Count
    matched_unique_keys = @($gbaByKey.Keys | Where-Object { $rpcByKey.ContainsKey($_) }).Count
    missing_in_rpc = $missingCount
    extra_in_rpc = $extraCount
    rpc_duplicate_key_groups = $rpcDuplicateGroups.Count
    rpc_duplicate_rows_beyond_first = $rpcDuplicateRowsBeyondFirst
    gba_duplicate_key_groups = $gbaDuplicateGroups.Count
    gba_duplicate_rows_beyond_first = $gbaDuplicateRowsBeyondFirst
    topics_mismatches = $topicsMismatchCount
    raw_data_mismatches = $dataMismatchCount
    comparison_pass = $comparisonPass
    rpc_requests_total = $metrics.rpc_attempts_total
    eth_getLogs_requests = $metrics.eth_getLogs_attempts
    successful_block_ranges = $metrics.successful_block_ranges
    rpc_retries = $metrics.rpc_retries
    rpc_error_attempts = $metrics.rpc_error_attempts
    adaptive_range_reductions = $metrics.adaptive_range_reductions
    adaptive_range_expansions = $metrics.adaptive_range_expansions
    rpc_response_bytes_total = $metrics.rpc_response_bytes_total
    eth_getLogs_response_bytes = $metrics.eth_getLogs_response_bytes
    shard_file_bytes = $shardFileBytes
    verified_shard_count = $rangeRecords.Count
    manifest_gap_count = $manifestGapCount
    manifest_overlap_count = $manifestOverlapCount
    manifest_part_files_remaining = $partFilesRemaining
    completed_ranges_refetched = $completedRangesRefetched
    resume_loaded_shards_preserved = $resumeLoadedShardsPreserved
    manifest_integrity_pass = $manifestIntegrityPass
    gba_reference_file_bytes = (Get-Item -LiteralPath $gbaReferencePath).Length
    successful_eth_getLogs_elapsed_seconds = [math]::Round($successfulGetLogsElapsedMs / 1000, 3)
    gba_query_elapsed_seconds = $gbaQueryElapsedSeconds
    current_run_collection_elapsed_seconds = [math]::Round($collectionWatch.Elapsed.TotalSeconds, 3)
    current_run_total_elapsed_seconds = [math]::Round($runWatch.Elapsed.TotalSeconds, 3)
    checkpoint_resumed = $checkpointWasLoaded
    intentional_resume_test = $null -ne $resumeEvidenceFinal
    resume_checkpoint_ranges = if ($null -ne $resumeCheckpointEvidence) { [int]$resumeCheckpointEvidence.completed_ranges } else { 0 }
    resume_checkpoint_rows = if ($null -ne $resumeCheckpointEvidence) { [int]$resumeCheckpointEvidence.checkpoint_log_rows } else { 0 }
    resume_checkpoint_duplicate_rows = if ($null -ne $resumeCheckpointEvidence) { [int]$resumeCheckpointEvidence.checkpoint_duplicate_rows } else { 0 }
    execution_started_utc = $executionStartedUtc.ToString('o')
    execution_ended_utc = $executionEndedUtc.ToString('o')
    manifest_path = 'data/tmp/' + (Split-Path -Leaf $outputRoot) + '/manifest.json'
}
Write-AtomicText -Path $summaryJsonPath -Text ($summary | ConvertTo-Json -Depth 8)
Write-ObjectsCsv -Path $summaryCsvPath -Rows @([pscustomobject]$summary) -EmptyHeader @()

$summary | ConvertTo-Json -Depth 8
if (-not $comparisonPass) { exit 3 }

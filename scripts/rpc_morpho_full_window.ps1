[CmdletBinding()]
param(
    [string]$RpcUrl = 'https://arb1.arbitrum.io/rpc',
    [datetime]$StartUtc = [datetime]'2025-07-09T13:00:00Z',
    [datetime]$EndExclusiveUtc = [datetime]'2026-08-18T00:00:00Z',
    [int]$InitialBlockSpan = 40000,
    [int]$MaximumBlockSpan = 80000,
    [int]$MaximumRetries = 3,
    [int]$MaximumConsecutiveRangeFailures = 6,
    [double]$MinimumFreeGiB = 5,
    [switch]$ConfirmFullWindow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ConfirmFullWindow) {
    throw 'Full-window extraction requires the explicit -ConfirmFullWindow switch.'
}
$authorizedStartUnix = [DateTimeOffset]::Parse('2025-07-09T13:00:00Z').ToUnixTimeSeconds()
$authorizedEndUnix = [DateTimeOffset]::Parse('2026-08-18T00:00:00Z').ToUnixTimeSeconds()
$requestedStartUnix = ([DateTimeOffset]$StartUtc.ToUniversalTime()).ToUnixTimeSeconds()
$requestedEndUnix = ([DateTimeOffset]$EndExclusiveUtc.ToUniversalTime()).ToUnixTimeSeconds()
if ($requestedStartUnix -ne $authorizedStartUnix -or $requestedEndUnix -ne $authorizedEndUnix) {
    throw 'This runner is restricted to the user-authorized full-window UTC boundaries.'
}

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$rawParent = Join-Path $workspaceRoot 'data/raw'
$outputRoot = Join-Path $rawParent 'morpho_full_window'
$shardRoot = Join-Path $outputRoot 'shards'
$manifestPath = Join-Path $outputRoot 'manifest.json'
$errorPath = Join-Path $outputRoot 'rpc_errors.csv'
$failurePath = Join-Path $outputRoot 'failed_range.json'
$marketCsvPath = Join-Path $workspaceRoot 'data/drip_morpho_markets.csv'
$gitignorePath = Join-Path $workspaceRoot '.gitignore'

$resolvedRawParent = [System.IO.Path]::GetFullPath($rawParent).TrimEnd('\') + '\'
$resolvedOutputRoot = [System.IO.Path]::GetFullPath($outputRoot)
if (-not $resolvedOutputRoot.StartsWith($resolvedRawParent, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output root must remain under data/raw: $resolvedOutputRoot"
}
if (-not (Select-String -LiteralPath $gitignorePath -Pattern '^data/raw/$' -Quiet)) {
    throw 'Required data/raw/ rule is missing from .gitignore.'
}
$outputDrive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($resolvedOutputRoot))
$freeBytesAtStart = [int64]$outputDrive.AvailableFreeSpace
$minimumFreeBytes = [int64]($MinimumFreeGiB * 1GB)
if ($freeBytesAtStart -lt $minimumFreeBytes) {
    throw "Insufficient free space: $([math]::Round($freeBytesAtStart / 1GB, 3)) GiB available; $MinimumFreeGiB GiB required."
}

New-Item -ItemType Directory -Path $shardRoot -Force | Out-Null

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$morphoAddress = '0x6c247b1f6182318877311737bac0844baa518f5e'
$eventHashToName = [ordered]@{
    '0xedf8870433c83823eb071d3df1caa8d008f12f6440918c20d75a3602cda30fe0' = 'Supply'
    '0xa56fc0ad5702ec05ce63666221f796fb62437c32db1aa1aa075fc6484cf58fbf' = 'Withdraw'
    '0x570954540bed6b1304a87dfe815a5eda4a648f7097a16240dcd85c9b5fd42a43' = 'Borrow'
    '0x52acb05cebbd3cd39715469f22afbf5a17496295ef3bc9bb5944056c63ccaa09' = 'Repay'
    '0xa3b9472a1399e17e123f3c2e6586c23e504184d504de59cdaa2b375e880c6184' = 'SupplyCollateral'
    '0xe80ebd7cc9223d7382aab2e0d1d6155c65651f83d53c8b9b06901d167e321142' = 'WithdrawCollateral'
    '0xa4946ede45d0c6f06a0f5ce92c9ad3b4751452d2fe0e25010783bcab57a67e41' = 'Liquidate'
    '0x9d9bd501d0657d7dfe415f779a620a62b78bc508ddc0891fbbd8b7ac0f8fce87' = 'AccrueInterest'
}
$eventHashes = @($eventHashToName.Keys)
$marketIds = @((Import-Csv -LiteralPath $marketCsvPath).market_id | ForEach-Object { $_.ToLowerInvariant() })
if ($marketIds.Count -ne 45 -or @($marketIds | Sort-Object -Unique).Count -ne 45) {
    throw "Expected 45 unique eligible market IDs, found $($marketIds.Count)."
}
$marketIdSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($marketId in $marketIds) { [void]$marketIdSet.Add($marketId) }

$metrics = [ordered]@{
    rpc_attempts_total = 0
    rpc_successful_responses = 0
    rpc_error_attempts = 0
    rpc_retries = 0
    rpc_response_bytes_total = [int64]0
    eth_getLogs_attempts = 0
    eth_getLogs_successful_responses = 0
    eth_getLogs_response_bytes = [int64]0
    block_lookup_attempts = 0
    successful_block_ranges = 0
    adaptive_range_reductions = 0
    adaptive_range_expansions = 0
}
$familyTotals = [ordered]@{}
foreach ($family in $eventHashToName.Values) { $familyTotals[$family] = [int64]0 }
$errorRecords = [System.Collections.Generic.List[object]]::new()
$rangeRecords = [System.Collections.Generic.List[object]]::new()
$seenKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$blockTimestampCache = @{}
$requestId = 0
$rowCount = [int64]0
$removedLogCount = [int64]0
$runStartedUtc = [datetime]::UtcNow
$runWatch = [System.Diagnostics.Stopwatch]::StartNew()

function Add-Metric {
    param([string]$Name, [int64]$Amount = 1)
    $script:metrics[$Name] = [int64]$script:metrics[$Name] + $Amount
}

function Write-AtomicText {
    param([string]$Path, [string]$Text)
    $resolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $Path))
    $resolvedWorkspace = [System.IO.Path]::GetFullPath($script:workspaceRoot).TrimEnd('\') + '\'
    if (-not (($resolvedParent.TrimEnd('\') + '\').StartsWith($resolvedWorkspace, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Refusing to write outside workspace: $Path"
    }
    $partPath = "$Path.part"
    [System.IO.File]::WriteAllText($partPath, $Text, $script:utf8NoBom)
    Move-Item -LiteralPath $partPath -Destination $Path -Force
}

function Write-ObjectsCsv {
    param([string]$Path, [object[]]$Rows, [string[]]$EmptyHeader)
    $text = if ($Rows.Count -gt 0) {
        ($Rows | ConvertTo-Csv -NoTypeInformation) -join [Environment]::NewLine
    } else {
        ($EmptyHeader | ForEach-Object { '"' + $_.Replace('"', '""') + '"' }) -join ','
    }
    Write-AtomicText -Path $Path -Text ($text + [Environment]::NewLine)
}

function Get-Sha256Lower {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function Normalize-TopicsJson {
    param([object[]]$Topics)
    return (@($Topics | ForEach-Object { ([string]$_).ToLowerInvariant() }) | ConvertTo-Json -Compress)
}

function Get-Key {
    param($Row)
    return "$($Row.block_number)|$(([string]$Row.transaction_hash).ToLowerInvariant())|$($Row.log_index)"
}

function Invoke-RpcRequest {
    param([string]$Method, [object[]]$Parameters)
    $lastException = $null
    for ($attempt = 1; $attempt -le ($script:MaximumRetries + 1); $attempt++) {
        $script:requestId++
        Add-Metric -Name 'rpc_attempts_total'
        if ($Method -eq 'eth_getLogs') { Add-Metric -Name 'eth_getLogs_attempts' }
        if ($Method -eq 'eth_getBlockByNumber') { Add-Metric -Name 'block_lookup_attempts' }
        $body = [ordered]@{ jsonrpc='2.0'; id=$script:requestId; method=$Method; params=$Parameters } | ConvertTo-Json -Depth 20 -Compress
        $callWatch = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-WebRequest -UseBasicParsing -DisableKeepAlive -Uri $script:RpcUrl -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 60
            $content = [string]$response.Content
            $responseBytes = [System.Text.Encoding]::UTF8.GetByteCount($content)
            Add-Metric -Name 'rpc_response_bytes_total' -Amount $responseBytes
            if ($Method -eq 'eth_getLogs') { Add-Metric -Name 'eth_getLogs_response_bytes' -Amount $responseBytes }
            $json = $content | ConvertFrom-Json -Depth 30
            if ($null -ne $json.PSObject.Properties['error'] -and $null -ne $json.error) {
                throw "RPC error $($json.error.code): $($json.error.message)"
            }
            Add-Metric -Name 'rpc_successful_responses'
            if ($Method -eq 'eth_getLogs') { Add-Metric -Name 'eth_getLogs_successful_responses' }
            $callWatch.Stop()
            return [pscustomobject]@{ result=$json.result; response_bytes=$responseBytes; attempts=$attempt; elapsed_ms=$callWatch.ElapsedMilliseconds }
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
    if ($script:blockTimestampCache.ContainsKey($cacheKey)) { return [int64]$script:blockTimestampCache[$cacheKey] }
    $envelope = Invoke-RpcRequest -Method 'eth_getBlockByNumber' -Parameters @((Convert-ToHexQuantity $BlockNumber), $false)
    if ($null -eq $envelope.result) { throw "Block $BlockNumber was not returned by RPC." }
    $timestamp = Convert-FromHexQuantity ([string]$envelope.result.timestamp)
    $script:blockTimestampCache[$cacheKey] = $timestamp
    return $timestamp
}

function Find-FirstBlockAtOrAfter {
    param([int64]$TargetUnix, [int64]$LatestBlock)
    if ((Get-BlockTimestampUnix $LatestBlock) -lt $TargetUnix) { throw 'Target timestamp is after the latest RPC block.' }
    [int64]$low = 0
    [int64]$high = $LatestBlock
    while ($low -lt $high) {
        [int64]$mid = $low + [math]::Floor(($high - $low) / 2)
        if ((Get-BlockTimestampUnix $mid) -ge $TargetUnix) { $high = $mid } else { $low = $mid + 1 }
    }
    return $low
}

function Get-CanonicalScopeHash {
    $scope = [ordered]@{
        contract_address = $script:morphoAddress
        event_hashes = @($script:eventHashes)
        market_ids = @($script:marketIds | Sort-Object)
    } | ConvertTo-Json -Depth 6 -Compress
    $bytes = $script:utf8NoBom.GetBytes($scope)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([Convert]::ToHexString($sha.ComputeHash($bytes))).ToLowerInvariant() } finally { $sha.Dispose() }
}

function Save-Manifest {
    param(
        [int64]$StartBlock,
        [int64]$EndBlockExclusive,
        [int64]$NextBlock,
        [int]$CurrentSpan,
        [bool]$Complete
    )
    Write-ObjectsCsv -Path $script:errorPath -Rows $script:errorRecords.ToArray() -EmptyHeader @('occurred_at_utc','method','attempt','message')
    $manifest = [ordered]@{
        version = 1
        storage = 'append-only immutable JSONL range shards'
        source = 'official Arbitrum One public RPC eth_getLogs; no full-window GBA query'
        contract_address = $script:morphoAddress
        event_hashes = @($script:eventHashes)
        market_ids = @($script:marketIds | Sort-Object)
        scope_sha256 = Get-CanonicalScopeHash
        start_utc = $script:StartUtc.ToUniversalTime().ToString('o')
        end_exclusive_utc = $script:EndExclusiveUtc.ToUniversalTime().ToString('o')
        start_block = $StartBlock
        end_block_exclusive = $EndBlockExclusive
        next_block = $NextBlock
        current_span = $CurrentSpan
        status = if ($Complete) { 'complete' } else { 'in_progress' }
        complete = $Complete
        verified_shard_count = $script:rangeRecords.Count
        row_count = $script:rowCount
        removed_log_count = $script:removedLogCount
        event_family_counts = $script:familyTotals
        shards = @($script:rangeRecords.ToArray())
        metrics = $script:metrics
        preflight = [ordered]@{
            output_root = $script:resolvedOutputRoot
            gitignore_rule = 'data/raw/'
            minimum_free_gib = $script:MinimumFreeGiB
            free_bytes_at_run_start = $script:freeBytesAtStart
        }
        updated_at_utc = [datetime]::UtcNow.ToString('o')
    }
    Write-AtomicText -Path $script:manifestPath -Text ($manifest | ConvertTo-Json -Depth 16)
}

function Get-RangeProfile {
    param([object[]]$RangeLogs)
    $rows = [System.Collections.Generic.List[object]]::new()
    $counts = [ordered]@{}
    foreach ($family in $script:eventHashToName.Values) { $counts[$family] = [int64]0 }
    $removed = [int64]0
    foreach ($log in $RangeLogs) {
        $topics = @($log.topics | ForEach-Object { ([string]$_).ToLowerInvariant() })
        if ($topics.Count -lt 2) { throw 'RPC log has fewer than two topics.' }
        $topic0 = $topics[0]
        $topic1 = $topics[1]
        if (-not $script:eventHashToName.Contains($topic0)) { throw "Unexpected event topic0: $topic0" }
        if (-not $script:marketIdSet.Contains($topic1)) { throw "Unexpected market topic1: $topic1" }
        if (([string]$log.address).ToLowerInvariant() -cne $script:morphoAddress) { throw "Unexpected log address: $($log.address)" }
        $family = [string]$script:eventHashToName[$topic0]
        $counts[$family] = [int64]$counts[$family] + 1
        if ([bool]$log.removed) { $removed++ }
        $rows.Add([pscustomobject]@{
            block_number = Convert-FromHexQuantity ([string]$log.blockNumber)
            transaction_hash = ([string]$log.transactionHash).ToLowerInvariant()
            transaction_index = Convert-FromHexQuantity ([string]$log.transactionIndex)
            log_index = Convert-FromHexQuantity ([string]$log.logIndex)
            address = ([string]$log.address).ToLowerInvariant()
            topics_json = Normalize-TopicsJson $topics
            data = ([string]$log.data).ToLowerInvariant()
            removed = [bool]$log.removed
        })
    }
    return [pscustomobject]@{ rows=@($rows.ToArray()); row_count=$rows.Count; removed_count=$removed; family_counts=$counts }
}

function Write-ImmutableShard {
    param([int]$RangeId, [int64]$FromBlock, [int64]$ToBlockExclusive, [object[]]$Rows)
    $fileName = ('range_{0:d6}_{1}_{2}.jsonl' -f $RangeId, $FromBlock, $ToBlockExclusive)
    $finalPath = Join-Path $script:shardRoot $fileName
    $partPath = "$finalPath.part"
    if ((Test-Path -LiteralPath $finalPath) -or (Test-Path -LiteralPath $partPath)) {
        throw "Refusing to overwrite immutable shard or .part: $fileName"
    }
    $payload = if ($Rows.Count -eq 0) { '' } else {
        (($Rows | ForEach-Object { $_ | ConvertTo-Json -Depth 12 -Compress }) -join [Environment]::NewLine) + [Environment]::NewLine
    }
    [System.IO.File]::WriteAllText($partPath, $payload, $script:utf8NoBom)
    $partChecksum = Get-Sha256Lower -Path $partPath
    Move-Item -LiteralPath $partPath -Destination $finalPath
    $finalChecksum = Get-Sha256Lower -Path $finalPath
    if ($partChecksum -cne $finalChecksum) { throw "Checksum changed during atomic shard rename: $fileName" }
    return [pscustomobject]@{ file=$fileName; checksum_sha256=$finalChecksum; file_bytes=(Get-Item -LiteralPath $finalPath).Length }
}

function Validate-Shard {
    param([object]$Entry, [System.Collections.Generic.HashSet[string]]$SeenKeys)
    if ([string]$Entry.status -cne 'verified') { throw "Shard $($Entry.range_id) is not verified." }
    $fileName = [string]$Entry.file
    if ([System.IO.Path]::GetFileName($fileName) -cne $fileName) { throw "Unsafe shard filename: $fileName" }
    $path = Join-Path $script:shardRoot $fileName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing shard: $fileName" }
    if ((Get-Sha256Lower -Path $path) -cne ([string]$Entry.checksum_sha256).ToLowerInvariant()) { throw "Checksum mismatch: $fileName" }
    $counts = [ordered]@{}
    foreach ($family in $script:eventHashToName.Values) { $counts[$family] = [int64]0 }
    [int64]$actualRows = 0
    [int64]$actualRemoved = 0
    foreach ($line in @(Get-Content -LiteralPath $path)) {
        if ([string]::IsNullOrWhiteSpace([string]$line)) { continue }
        $row = [string]$line | ConvertFrom-Json -Depth 20
        $block = [int64]$row.block_number
        if ($block -lt [int64]$Entry.from_block -or $block -ge [int64]$Entry.to_block_exclusive) {
            throw "Row block $block is outside shard $fileName boundaries."
        }
        if ([string]$row.address -cne $script:morphoAddress) { throw "Unexpected address in shard $fileName." }
        $topics = @($row.topics_json | ConvertFrom-Json)
        if ($topics.Count -lt 2) { throw "Too few topics in shard $fileName." }
        $topic0 = ([string]$topics[0]).ToLowerInvariant()
        $topic1 = ([string]$topics[1]).ToLowerInvariant()
        if (-not $script:eventHashToName.Contains($topic0)) { throw "Unexpected topic0 in shard $fileName." }
        if (-not $script:marketIdSet.Contains($topic1)) { throw "Unexpected market ID in shard $fileName." }
        $family = [string]$script:eventHashToName[$topic0]
        $counts[$family] = [int64]$counts[$family] + 1
        if ([bool]$row.removed) { $actualRemoved++ }
        $key = Get-Key $row
        if (-not $SeenKeys.Add($key)) { throw "Duplicate event key while validating shards: $key" }
        $actualRows++
    }
    if ($actualRows -ne [int64]$Entry.row_count) { throw "Row-count mismatch for ${fileName}: manifest=$($Entry.row_count), actual=$actualRows." }
    if ($actualRemoved -ne [int64]$Entry.removed_count) { throw "Removed-count mismatch for $fileName." }
    foreach ($family in $script:eventHashToName.Values) {
        $savedCount = if ($Entry.event_family_counts -is [System.Collections.IDictionary]) {
            [int64]$Entry.event_family_counts[[string]$family]
        } else {
            $savedProperty = $Entry.event_family_counts.PSObject.Properties[[string]$family]
            if ($null -eq $savedProperty) { [int64]0 } else { [int64]$savedProperty.Value }
        }
        if ([int64]$counts[[string]$family] -ne $savedCount) { throw "Event-family count mismatch for $family in $fileName." }
    }
    return [pscustomobject]@{ row_count=$actualRows; removed_count=$actualRemoved; family_counts=$counts }
}

function Write-FailedRange {
    param([int64]$FromBlock, [int64]$ToBlockExclusive, [int]$Span, [int]$ConsecutiveFailures, [string]$Message)
    $failure = [ordered]@{
        status = 'stopped_on_unrecoverable_rpc_error'
        from_block = $FromBlock
        to_block_exclusive = $ToBlockExclusive
        attempted_span = $Span
        consecutive_range_failures = $ConsecutiveFailures
        maximum_retries_per_request = $script:MaximumRetries
        message = $Message
        manifest_next_block = $FromBlock
        occurred_at_utc = [datetime]::UtcNow.ToString('o')
    }
    Write-AtomicText -Path $script:failurePath -Text ($failure | ConvertTo-Json -Depth 8)
}

[int64]$startBlock = 0
[int64]$endBlockExclusive = 0
[int64]$nextBlock = 0
[int]$currentSpan = $InitialBlockSpan
$manifestLoaded = $false
$chainId = 42161

if (Test-Path -LiteralPath $manifestPath) {
    $manifestLoaded = $true
    $saved = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -Depth 30
    if ([int]$saved.version -ne 1) { throw "Unsupported full-window manifest version: $($saved.version)" }
    if ([datetime]$saved.start_utc -ne $StartUtc.ToUniversalTime() -or [datetime]$saved.end_exclusive_utc -ne $EndExclusiveUtc.ToUniversalTime()) {
        throw 'Manifest UTC boundaries differ from the authorized window.'
    }
    if ([string]$saved.contract_address -cne $morphoAddress -or [string]$saved.scope_sha256 -cne (Get-CanonicalScopeHash)) {
        throw 'Manifest extraction scope differs from the current contract/events/markets scope.'
    }
    foreach ($property in $saved.metrics.PSObject.Properties) {
        if ($metrics.Contains($property.Name)) { $metrics[$property.Name] = [int64]$property.Value }
    }
    if (Test-Path -LiteralPath $errorPath) {
        foreach ($row in @(Import-Csv -LiteralPath $errorPath)) { $errorRecords.Add($row) }
    }
    $partFiles = @(Get-ChildItem -LiteralPath $shardRoot -Filter '*.part' -File)
    if ($partFiles.Count -gt 0) { throw "Orphan .part shard(s) require review: $($partFiles.Name -join ', ')" }
    $startBlock = [int64]$saved.start_block
    $endBlockExclusive = [int64]$saved.end_block_exclusive
    $nextBlock = [int64]$saved.next_block
    $currentSpan = [int]$saved.current_span
    [int64]$expectedBlock = $startBlock
    [int]$expectedRangeId = 1
    $manifestFiles = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($entry in @($saved.shards)) {
        if ([int]$entry.range_id -ne $expectedRangeId) { throw "Manifest range_id breaks at $expectedRangeId." }
        if ([int64]$entry.from_block -ne $expectedBlock) { throw "Manifest gap/overlap before range $expectedRangeId." }
        if ([int64]$entry.to_block_exclusive -le [int64]$entry.from_block -or [int64]$entry.to_block_exclusive -gt $endBlockExclusive) { throw "Invalid boundaries in range $expectedRangeId." }
        if (-not $manifestFiles.Add([string]$entry.file)) { throw "Duplicate manifest filename: $($entry.file)" }
        $profile = Validate-Shard -Entry $entry -SeenKeys $seenKeys
        $rowCount += [int64]$profile.row_count
        $removedLogCount += [int64]$profile.removed_count
        foreach ($family in $eventHashToName.Values) { $familyTotals[[string]$family] += [int64]$profile.family_counts[[string]$family] }
        $rangeRecords.Add($entry)
        $expectedBlock = [int64]$entry.to_block_exclusive
        $expectedRangeId++
    }
    if ($expectedBlock -ne $nextBlock) { throw 'Manifest next_block does not follow the last verified shard.' }
    if ($rangeRecords.Count -ne [int]$saved.verified_shard_count -or $rowCount -ne [int64]$saved.row_count) { throw 'Manifest aggregate counts do not match verified shards.' }
    $orphanFinal = @(Get-ChildItem -LiteralPath $shardRoot -Filter '*.jsonl' -File | Where-Object { -not $manifestFiles.Contains($_.Name) })
    if ($orphanFinal.Count -gt 0) { throw "Final shard(s) are not referenced by manifest: $($orphanFinal.Name -join ', ')" }
    Write-Host "Verified manifest: status=$($saved.status), shards=$($rangeRecords.Count), rows=$rowCount, next_block=$nextBlock."
} else {
    $orphanFiles = @(Get-ChildItem -LiteralPath $shardRoot -File | Where-Object { $_.Name -like '*.jsonl' -or $_.Name -like '*.part' })
    if ($orphanFiles.Count -gt 0) { throw "Shard files exist without a manifest: $($orphanFiles.Name -join ', ')" }
    $chainEnvelope = Invoke-RpcRequest -Method 'eth_chainId' -Parameters @()
    $chainId = Convert-FromHexQuantity ([string]$chainEnvelope.result)
    if ($chainId -ne 42161) { throw "Unexpected chain ID: $chainId" }
    $latestEnvelope = Invoke-RpcRequest -Method 'eth_blockNumber' -Parameters @()
    $latestBlock = Convert-FromHexQuantity ([string]$latestEnvelope.result)
    $startUnix = ([DateTimeOffset]$StartUtc.ToUniversalTime()).ToUnixTimeSeconds()
    $endUnix = ([DateTimeOffset]$EndExclusiveUtc.ToUniversalTime()).ToUnixTimeSeconds()
    $startBlock = Find-FirstBlockAtOrAfter -TargetUnix $startUnix -LatestBlock $latestBlock
    $endBlockExclusive = Find-FirstBlockAtOrAfter -TargetUnix $endUnix -LatestBlock $latestBlock
    $nextBlock = $startBlock
    Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
}

Write-Host "Preflight PASS: free=$([math]::Round($freeBytesAtStart / 1GB, 3)) GiB; ignored=data/raw/; output=$resolvedOutputRoot"
Write-Host "Authorized block interval: [$startBlock, $endBlockExclusive) ($($endBlockExclusive - $startBlock) blocks)."

$chainCheck = Invoke-RpcRequest -Method 'eth_chainId' -Parameters @()
$chainId = Convert-FromHexQuantity ([string]$chainCheck.result)
if ($chainId -ne 42161) { throw "Unexpected chain ID on active RPC: $chainId" }

$consecutiveRangeFailures = 0
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
        $consecutiveRangeFailures = 0
    } catch {
        $consecutiveRangeFailures++
        $message = $_.Exception.Message
        if ($currentSpan -le 1 -or $consecutiveRangeFailures -ge $MaximumConsecutiveRangeFailures) {
            Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
            Write-FailedRange -FromBlock $nextBlock -ToBlockExclusive ($toBlock + 1) -Span $currentSpan -ConsecutiveFailures $consecutiveRangeFailures -Message $message
            throw "Unrecoverable RPC range [$nextBlock, $($toBlock + 1)): $message"
        }
        $currentSpan = [math]::Max(1, [math]::Floor($currentSpan / 2))
        Add-Metric -Name 'adaptive_range_reductions'
        Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
        Write-Warning "Range failed; checkpoint preserved at $nextBlock. Reducing span to $currentSpan."
        continue
    }

    $rangeLogs = @($envelope.result)
    $profile = Get-RangeProfile -RangeLogs $rangeLogs
    $nextSpan = $currentSpan
    if ($profile.row_count -lt 150 -and $currentSpan -lt $MaximumBlockSpan) {
        $nextSpan = [math]::Min($MaximumBlockSpan, $currentSpan * 2)
        if ($nextSpan -ne $currentSpan) { Add-Metric -Name 'adaptive_range_expansions' }
    } elseif ($profile.row_count -gt 1000 -and $currentSpan -gt 1) {
        $nextSpan = [math]::Max(1, [math]::Floor($currentSpan / 2))
        if ($nextSpan -ne $currentSpan) { Add-Metric -Name 'adaptive_range_reductions' }
    }

    $rangeId = $rangeRecords.Count + 1
    $shard = Write-ImmutableShard -RangeId $rangeId -FromBlock $nextBlock -ToBlockExclusive ($toBlock + 1) -Rows $profile.rows
    $entry = [pscustomobject]@{
        range_id = $rangeId
        status = 'verified'
        from_block = $nextBlock
        to_block_exclusive = $toBlock + 1
        block_count = $toBlock - $nextBlock + 1
        row_count = [int64]$profile.row_count
        removed_count = [int64]$profile.removed_count
        event_family_counts = $profile.family_counts
        file = $shard.file
        checksum_algorithm = 'SHA256'
        checksum_sha256 = $shard.checksum_sha256
        file_bytes = [int64]$shard.file_bytes
        attempts = $envelope.attempts
        elapsed_ms = $envelope.elapsed_ms
        response_bytes = $envelope.response_bytes
        next_span = $nextSpan
        completed_at_utc = [datetime]::UtcNow.ToString('o')
    }
    $validated = Validate-Shard -Entry $entry -SeenKeys $seenKeys
    $rowCount += [int64]$validated.row_count
    $removedLogCount += [int64]$validated.removed_count
    foreach ($family in $eventHashToName.Values) { $familyTotals[[string]$family] += [int64]$validated.family_counts[[string]$family] }
    $rangeRecords.Add($entry)
    Add-Metric -Name 'successful_block_ranges'
    $nextBlock = $toBlock + 1
    $currentSpan = $nextSpan
    Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $false
    $coveragePct = [math]::Round((($nextBlock - $startBlock) / [double]($endBlockExclusive - $startBlock)) * 100, 3)
    Write-Host "Range $rangeId verified: [$($entry.from_block), $($entry.to_block_exclusive)) rows=$($entry.row_count) total_rows=$rowCount coverage=$coveragePct% next_span=$currentSpan"
}

Save-Manifest -StartBlock $startBlock -EndBlockExclusive $endBlockExclusive -NextBlock $nextBlock -CurrentSpan $currentSpan -Complete $true
$runWatch.Stop()
$summary = [ordered]@{
    status = 'complete'
    start_utc = $StartUtc.ToUniversalTime().ToString('o')
    end_exclusive_utc = $EndExclusiveUtc.ToUniversalTime().ToString('o')
    start_block = $startBlock
    end_block_exclusive = $endBlockExclusive
    block_count = $endBlockExclusive - $startBlock
    verified_shards = $rangeRecords.Count
    rows = $rowCount
    unique_keys = $seenKeys.Count
    removed_logs = $removedLogCount
    event_family_counts = $familyTotals
    rpc_attempts_total = $metrics.rpc_attempts_total
    eth_getLogs_attempts = $metrics.eth_getLogs_attempts
    retries = $metrics.rpc_retries
    error_attempts = $metrics.rpc_error_attempts
    response_bytes = $metrics.rpc_response_bytes_total
    shard_bytes = [int64](($rangeRecords.ToArray() | Measure-Object -Property file_bytes -Sum).Sum)
    manifest_loaded = $manifestLoaded
    current_run_elapsed_seconds = [math]::Round($runWatch.Elapsed.TotalSeconds, 3)
    current_run_started_utc = $runStartedUtc.ToString('o')
    completed_at_utc = [datetime]::UtcNow.ToString('o')
    manifest_path = $manifestPath
}
$summary | ConvertTo-Json -Depth 12

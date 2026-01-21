<script>
    import { onMount } from 'svelte';
    import { api } from '../../api/client.js';
    import { toasts } from '../../stores/toast.js';
    import { Card } from '@myorg/ui';
    import { Button } from '@myorg/ui';
    import { Modal } from '@myorg/ui';
    
    // Tab state
    let activeTab = 'tracing';  // 'tracing', 'logs', or 'database'
    
    // State
    let loading = true;
    let overview = null;
    let requests = [];
    let selectedTrace = null;
    let showDrilldown = false;
    
    // Services
    let services = [];
    let currentService = '';
    let selectedService = '';  // '' = all services
    
    // Filters
    let hours = 24;
    let pathPrefix = '';
    let minDuration = '';
    let statusClass = '';
    let limit = 50;
    
    // Backend Logs state
    let backendLogs = [];
    let logsLoading = false;
    let logLevel = '';
    let logSearch = '';
    let logLimit = 200;
    let autoRefreshLogs = false;
    let logsInterval = null;
    
    // Database state
    let dbInfo = null;
    let dbLoading = false;
    let dbUploading = false;
    let fileInput;
    
    // Load database info
    async function loadDbInfo() {
        dbLoading = true;
        try {
            dbInfo = await api('GET', '/admin/db/info');
        } catch (err) {
            toasts.error(`Failed to load db info: ${err.message}`);
            dbInfo = null;
        }
        dbLoading = false;
    }
    
    // Download database
    async function downloadDb() {
        try {
            // Use fetch directly for file download
            const token = localStorage.getItem('token');
            const response = await fetch(`${window.API_BASE_URL || ''}/api/v1/admin/db/download`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            
            if (!response.ok) {
                throw new Error(`Download failed: ${response.status}`);
            }
            
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'deploy.db';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            
            toasts.success('Database downloaded');
        } catch (err) {
            toasts.error(`Download failed: ${err.message}`);
        }
    }
    
    // Upload database
    async function uploadDb() {
        const file = fileInput?.files?.[0];
        if (!file) {
            toasts.error('Please select a file first');
            return;
        }
        
        if (!file.name.endsWith('.db')) {
            toasts.error('File must be a .db SQLite database');
            return;
        }
        
        if (!confirm('This will REPLACE the entire database! Make sure you downloaded a backup first. Continue?')) {
            return;
        }
        
        dbUploading = true;
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            const token = localStorage.getItem('token');
            const response = await fetch(`${window.API_BASE_URL || ''}/api/v1/admin/db/upload`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData
            });
            
            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || `Upload failed: ${response.status}`);
            }
            
            const result = await response.json();
            toasts.success(result.message || 'Database uploaded successfully');
            toasts.info('Restart the service for changes to take effect');
            
            // Refresh db info
            await loadDbInfo();
            
            // Clear file input
            if (fileInput) fileInput.value = '';
            
        } catch (err) {
            toasts.error(`Upload failed: ${err.message}`);
        }
        dbUploading = false;
    }
    
    // Load backend logs
    async function loadBackendLogs() {
        logsLoading = true;
        try {
            const params = new URLSearchParams({ limit: logLimit.toString() });
            if (logLevel) params.set('level', logLevel);
            if (logSearch) params.set('search', logSearch);
            
            backendLogs = await api('GET', `/admin/logs?${params}`);
        } catch (err) {
            toasts.error(`Failed to load logs: ${err.message}`);
            backendLogs = [];
        }
        logsLoading = false;
    }
    
    // Toggle auto-refresh for logs
    function toggleAutoRefresh() {
        autoRefreshLogs = !autoRefreshLogs;
        if (autoRefreshLogs) {
            logsInterval = setInterval(loadBackendLogs, 3000);
            toasts.info('Auto-refresh enabled (3s)');
        } else {
            clearInterval(logsInterval);
            logsInterval = null;
            toasts.info('Auto-refresh disabled');
        }
    }
    
    // Clear logs
    async function clearLogs() {
        try {
            await api('DELETE', '/admin/logs');
            backendLogs = [];
            toasts.info('Logs cleared');
        } catch (err) {
            toasts.error(`Failed to clear logs: ${err.message}`);
        }
    }
    
    // Log level color
    function logLevelColor(level) {
        switch (level) {
            case 'DEBUG': return '#888';
            case 'INFO': return '#4CAF50';
            case 'WARNING': return '#ff9800';
            case 'ERROR': return '#f44336';
            case 'CRITICAL': return '#9c27b0';
            default: return '#888';
        }
    }
    
    // Load available services
    async function loadServices() {
        try {
            const result = await api('GET', '/admin/telemetry/services');
            services = result.services || [];
            currentService = result.current || 'unknown';
        } catch (err) {
            console.warn('Could not load services:', err);
            services = [];
        }
    }
    
    // Load overview stats
    async function loadOverview() {
        try {
            const params = new URLSearchParams({ hours: hours.toString() });
            if (pathPrefix) params.set('path_prefix', pathPrefix);
            if (selectedService) params.set('service_name', selectedService);
            
            overview = await api('GET', `/admin/telemetry/overview?${params}`);
        } catch (err) {
            toasts.error(`Failed to load overview: ${err.message}`);
        }
    }
    
    // Load requests list
    async function loadRequests() {
        try {
            const params = new URLSearchParams({
                hours: hours.toString(),
                limit: limit.toString(),
            });
            if (pathPrefix) params.set('path_prefix', pathPrefix);
            if (minDuration) params.set('min_duration_ms', minDuration);
            if (statusClass) params.set('status_class', statusClass);
            if (selectedService) params.set('service_name', selectedService);
            
            requests = await api('GET', `/admin/telemetry/requests?${params}`);
        } catch (err) {
            toasts.error(`Failed to load requests: ${err.message}`);
        }
    }
    
    // Load trace detail for drill-down
    async function loadTraceDetail(requestId) {
        try {
            selectedTrace = await api('GET', `/admin/telemetry/requests/${requestId}`);
            showDrilldown = true;
        } catch (err) {
            toasts.error(`Failed to load trace: ${err.message}`);
        }
    }
    
    // Refresh all data
    async function refresh() {
        loading = true;
        await Promise.all([loadServices(), loadOverview(), loadRequests()]);
        loading = false;
    }
    
    // Load slow requests
    async function loadSlowRequests() {
        try {
            const params = new URLSearchParams({
                hours: hours.toString(),
                threshold_ms: '1000',
                limit: '50',
            });
            if (selectedService) params.set('service_name', selectedService);
            requests = await api('GET', `/admin/telemetry/slow?${params}`);
            toasts.info('Showing slow requests (>1s)');
        } catch (err) {
            toasts.error(`Failed to load slow requests: ${err.message}`);
        }
    }
    
    // Load error requests
    async function loadErrorRequests(errorClass = '5xx') {
        try {
            const params = new URLSearchParams({
                hours: hours.toString(),
                status_class: errorClass,
                limit: '50',
            });
            if (selectedService) params.set('service_name', selectedService);
            requests = await api('GET', `/admin/telemetry/errors?${params}`);
            toasts.info(`Showing ${errorClass} errors`);
        } catch (err) {
            toasts.error(`Failed to load errors: ${err.message}`);
        }
    }
    
    // Format duration
    function formatMs(ms) {
        if (!ms) return '-';
        if (ms < 1000) return `${Math.round(ms)}ms`;
        return `${(ms / 1000).toFixed(2)}s`;
    }
    
    // Format timestamp
    function formatTime(ts) {
        if (!ts) return '-';
        const d = new Date(ts);
        return d.toLocaleTimeString();
    }
    
    // Status color
    function statusColor(code) {
        if (!code) return 'gray';
        if (code < 300) return 'green';
        if (code < 400) return 'blue';
        if (code < 500) return 'yellow';
        return 'red';
    }
    
    // Calculate span bar width (percentage)
    function spanWidth(span, totalMs) {
        if (!span.duration_ms || !totalMs) return 0;
        return Math.max(2, (span.duration_ms / totalMs) * 100);
    }
    
    onMount(() => {
        refresh();
        return () => {
            // Cleanup on destroy
            if (logsInterval) clearInterval(logsInterval);
        };
    });
    
    // Handle tab change
    function switchTab(tab) {
        activeTab = tab;
        if (tab === 'logs' && backendLogs.length === 0) {
            loadBackendLogs();
        }
        if (tab === 'database' && !dbInfo) {
            loadDbInfo();
        }
    }
</script>

<div class="telemetry">
    <div class="header">
        <h2>🔍 Telemetry Dashboard</h2>
        <div class="tabs">
            <button 
                class="tab" 
                class:active={activeTab === 'tracing'} 
                on:click={() => switchTab('tracing')}
            >
                📊 Request Tracing
            </button>
            <button 
                class="tab" 
                class:active={activeTab === 'logs'} 
                on:click={() => switchTab('logs')}
            >
                📝 Backend Logs
            </button>
            <button 
                class="tab" 
                class:active={activeTab === 'database'} 
                on:click={() => switchTab('database')}
            >
                🗄️ Database
            </button>
            <button 
                class="tab" 
                class:active={activeTab === 'database'} 
                on:click={() => switchTab('database')}
            >
                🗄️ Database
            </button>
            <button 
                class="tab" 
                class:active={activeTab === 'database'} 
                on:click={() => switchTab('database')}
            >
                🗄️ Database
            </button>
        </div>
        <div class="controls">
            {#if activeTab === 'tracing'}
            <select bind:value={hours} on:change={refresh}>
                <option value={1}>Last 1 hour</option>
                <option value={6}>Last 6 hours</option>
                <option value={24}>Last 24 hours</option>
                <option value={168}>Last 7 days</option>
            </select>
            <Button on:click={refresh} disabled={loading}>
                {loading ? '⏳' : '🔄'} Refresh
            </Button>
            {:else}
            <select bind:value={logLevel} on:change={loadBackendLogs}>
                <option value="">All Levels</option>
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
            </select>
            <input 
                type="text" 
                placeholder="Search logs..." 
                bind:value={logSearch}
                on:keyup={(e) => e.key === 'Enter' && loadBackendLogs()}
            />
            <Button on:click={loadBackendLogs} disabled={logsLoading}>
                {logsLoading ? '⏳' : '🔄'} Refresh
            </Button>
            <Button on:click={toggleAutoRefresh} variant={autoRefreshLogs ? 'primary' : 'secondary'}>
                {autoRefreshLogs ? '⏸️ Stop' : '▶️ Auto'}
            </Button>
            <Button on:click={clearLogs} variant="danger">
                🗑️ Clear
            </Button>
            {/if}
        </div>
    </div>
    
    {#if activeTab === 'tracing'}
    
    <!-- Overview Cards -->
    {#if overview}
    <div class="overview-grid">
        <Card>
            <div class="stat">
                <span class="label">Total Requests</span>
                <span class="value">{overview.total_requests.toLocaleString()}</span>
            </div>
        </Card>
        <Card>
            <div class="stat">
                <span class="label">Avg Latency</span>
                <span class="value">{formatMs(overview.avg_latency_ms)}</span>
            </div>
        </Card>
        <Card>
            <div class="stat">
                <span class="label">P95 Latency</span>
                <span class="value">{formatMs(overview.p95_latency_ms)}</span>
            </div>
        </Card>
        <Card>
            <div class="stat" class:error={overview.error_rate > 5}>
                <span class="label">Error Rate</span>
                <span class="value">{overview.error_rate}%</span>
            </div>
        </Card>
        <Card>
            <div class="stat clickable" on:click={loadSlowRequests} on:keypress={loadSlowRequests}>
                <span class="label">Slow Requests</span>
                <span class="value">{overview.slow_count}</span>
            </div>
        </Card>
        <Card>
            <div class="stat clickable" on:click={() => loadErrorRequests('5xx')} on:keypress={() => loadErrorRequests('5xx')}>
                <span class="label">5xx Errors</span>
                <span class="value">{overview.error_count}</span>
            </div>
        </Card>
    </div>
    {/if}
    
    <!-- Slow Endpoints -->
    {#if overview?.slow_endpoints?.length > 0}
    <Card>
        <h3>🐢 Slowest Endpoints</h3>
        <table class="mini-table">
            <thead>
                <tr>
                    <th>Path</th>
                    <th>Avg</th>
                    <th>Count</th>
                </tr>
            </thead>
            <tbody>
                {#each overview.slow_endpoints.slice(0, 5) as ep}
                <tr>
                    <td class="path">{ep.path}</td>
                    <td>{formatMs(ep.avg_ms)}</td>
                    <td>{ep.count}</td>
                </tr>
                {/each}
            </tbody>
        </table>
    </Card>
    {/if}
    
    <!-- Filters -->
    <div class="filters">
        <select bind:value={selectedService} on:change={refresh} title="Filter by service">
            <option value="">All services</option>
            {#each services as svc}
            <option value={svc}>{svc} {svc === currentService ? '(current)' : ''}</option>
            {/each}
        </select>
        <input 
            type="text" 
            placeholder="Path prefix (e.g., /api/v1/infra)" 
            bind:value={pathPrefix}
            on:change={loadRequests}
        />
        <input 
            type="number" 
            placeholder="Min ms" 
            bind:value={minDuration}
            on:change={loadRequests}
        />
        <select bind:value={statusClass} on:change={loadRequests}>
            <option value="">All status</option>
            <option value="2xx">2xx Success</option>
            <option value="4xx">4xx Client Error</option>
            <option value="5xx">5xx Server Error</option>
        </select>
        <Button on:click={loadRequests} size="small">Apply</Button>
    </div>
    
    <!-- Requests Table -->
    <Card>
        <h3>📋 Recent Requests</h3>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Service</th>
                        <th>Method</th>
                        <th>Path</th>
                        <th>Status</th>
                        <th>Duration</th>
                        <th>Spans</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {#each requests as req}
                    <tr class:error={req.status_code >= 500} class:warning={req.status_code >= 400 && req.status_code < 500}>
                        <td class="time">{formatTime(req.timestamp)}</td>
                        <td class="service">{req.service_name || '-'}</td>
                        <td><span class="method {req.method?.toLowerCase()}">{req.method}</span></td>
                        <td class="path" title={req.path}>{req.path?.length > 40 ? req.path.slice(0, 40) + '...' : req.path}</td>
                        <td><span class="status status-{statusColor(req.status_code)}">{req.status_code || '-'}</span></td>
                        <td class:slow={req.duration_ms > 1000}>{formatMs(req.duration_ms)}</td>
                        <td>{req.span_count}</td>
                        <td>
                            <Button size="small" on:click={() => loadTraceDetail(req.request_id)}>
                                View
                            </Button>
                        </td>
                    </tr>
                    {/each}
                    {#if requests.length === 0}
                    <tr>
                        <td colspan="8" class="empty">No requests found</td>
                    </tr>
                    {/if}
                </tbody>
            </table>
        </div>
    </Card>
    
    {/if}
    <!-- End of tracing tab -->
    
    <!-- Backend Logs Tab -->
    {#if activeTab === 'logs'}
    <Card>
        <div class="logs-header">
            <h3>📝 Backend Logs</h3>
            <span class="log-count">{backendLogs.length} entries</span>
        </div>
        
        {#if logsLoading}
        <div class="loading-logs">Loading logs...</div>
        {:else if backendLogs.length === 0}
        <div class="empty-logs">
            <p>No logs found.</p>
            <p class="hint">Logs are captured in memory. They reset when the server restarts.</p>
        </div>
        {:else}
        <div class="logs-container">
            {#each backendLogs as log}
            <div class="log-entry" class:error={log.level === 'ERROR' || log.level === 'CRITICAL'} class:warning={log.level === 'WARNING'}>
                <span class="log-time">{log.timestamp?.split('T')[1]?.split('.')[0] || log.timestamp}</span>
                <span class="log-level" style="color: {logLevelColor(log.level)}">[{log.level}]</span>
                <span class="log-logger">{log.logger}</span>
                <span class="log-message">{log.message}</span>
                {#if log.module && log.funcName}
                <span class="log-location">({log.module}.{log.funcName}:{log.lineno})</span>
                {/if}
            </div>
            {/each}
        </div>
        {/if}
    </Card>
    {/if}
    <!-- End of logs tab -->
    
    <!-- Database Tab -->
    {#if activeTab === 'database'}
    <Card>
        <div class="db-section">
            <h3>🗄️ Database Management</h3>
            <p class="db-warning">⚠️ Dev phase only - Use with caution!</p>
            
            {#if dbLoading}
            <div class="loading-db">Loading database info...</div>
            {:else if dbInfo}
            <div class="db-info">
                <div class="db-info-row">
                    <span class="label">Path:</span>
                    <code>{dbInfo.path}</code>
                </div>
                <div class="db-info-row">
                    <span class="label">Status:</span>
                    <span class="status-badge" class:exists={dbInfo.exists}>
                        {dbInfo.exists ? '✅ Exists' : '❌ Not found'}
                    </span>
                </div>
                {#if dbInfo.exists}
                <div class="db-info-row">
                    <span class="label">Size:</span>
                    <span>{dbInfo.size_human}</span>
                </div>
                <div class="db-info-row">
                    <span class="label">Modified:</span>
                    <span>{dbInfo.modified}</span>
                </div>
                {/if}
            </div>
            {/if}
            
            <div class="db-actions">
                <div class="action-group">
                    <h4>📥 Download</h4>
                    <p>Download the current database to your local machine.</p>
                    <Button on:click={downloadDb} disabled={!dbInfo?.exists}>
                        📥 Download Database
                    </Button>
                </div>
                
                <div class="action-group">
                    <h4>📤 Upload</h4>
                    <p>Upload a database file to replace the server's database.</p>
                    <div class="upload-controls">
                        <input 
                            type="file" 
                            accept=".db"
                            bind:this={fileInput}
                            class="file-input"
                        />
                        <Button on:click={uploadDb} disabled={dbUploading} variant="danger">
                            {dbUploading ? '⏳ Uploading...' : '📤 Upload & Replace'}
                        </Button>
                    </div>
                    <p class="upload-warning">⚠️ This will REPLACE the entire database. Download a backup first!</p>
                </div>
            </div>
            
            <div class="db-footer">
                <Button on:click={loadDbInfo} disabled={dbLoading}>
                    🔄 Refresh Info
                </Button>
            </div>
        </div>
    </Card>
    {/if}
    <!-- End of database tab -->
    
</div>

<!-- Drill-down Modal -->
{#if showDrilldown && selectedTrace}
<Modal open={true} title="Request Detail" on:close={() => showDrilldown = false} width="800px">
    <div class="trace-detail">
        <div class="trace-header">
            {#if selectedTrace.service_name}
            <span class="service-badge">{selectedTrace.service_name}</span>
            {/if}
            <span class="method {selectedTrace.method?.toLowerCase()}">{selectedTrace.method}</span>
            <span class="path">{selectedTrace.path}</span>
            <span class="status status-{statusColor(selectedTrace.status_code)}">{selectedTrace.status_code}</span>
            <span class="duration">{formatMs(selectedTrace.duration_ms)}</span>
        </div>
        
        {#if selectedTrace.error}
        <div class="error-box">
            ⚠️ {selectedTrace.error}
        </div>
        {/if}
        
        <div class="trace-meta">
            <span>Request ID: <code>{selectedTrace.request_id}</code></span>
            {#if selectedTrace.user_id}
            <span>User: {selectedTrace.user_id}</span>
            {/if}
            <span>Time: {selectedTrace.timestamp}</span>
        </div>
        
        <h4>Timeline ({selectedTrace.spans.length} spans)</h4>
        <div class="spans-timeline">
            {#each selectedTrace.spans as span, i}
            <div class="span-row">
                <div class="span-name" title={span.name}>
                    {span.name}
                </div>
                <div class="span-bar-container">
                    <div 
                        class="span-bar" 
                        class:error={span.error}
                        style="width: {spanWidth(span, selectedTrace.total_ms)}%"
                    >
                        {formatMs(span.duration_ms)}
                    </div>
                </div>
            </div>
            
            <!-- Show child spans indented -->
            {#each span.children || [] as child}
            <div class="span-row child">
                <div class="span-name" title={child.name}>
                    └─ {child.name}
                </div>
                <div class="span-bar-container">
                    <div 
                        class="span-bar child-bar" 
                        class:error={child.error}
                        style="width: {spanWidth(child, selectedTrace.total_ms)}%"
                    >
                        {formatMs(child.duration_ms)}
                    </div>
                </div>
            </div>
            {/each}
            {/each}
        </div>
        
        <!-- Span Details -->
        {#if selectedTrace.spans.length > 0}
        <h4>Span Details</h4>
        <div class="spans-details">
            {#each selectedTrace.spans as span}
            <details>
                <summary>
                    <span class="span-kind">{span.kind}</span>
                    {span.name} - {formatMs(span.duration_ms)}
                    {#if span.error}<span class="error-badge">ERROR</span>{/if}
                </summary>
                <div class="span-attrs">
                    {#each Object.entries(span.attributes) as [key, value]}
                    <div class="attr">
                        <span class="key">{key}:</span>
                        <span class="value">{typeof value === 'object' ? JSON.stringify(value) : value}</span>
                    </div>
                    {/each}
                    {#if span.error}
                    <div class="attr error">
                        <span class="key">error:</span>
                        <span class="value">{span.error}</span>
                    </div>
                    {/if}
                </div>
            </details>
            {/each}
        </div>
        {/if}
    </div>
</Modal>
{/if}

<style>
    .telemetry {
        padding: 1rem;
    }
    
    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;
    }
    
    .header h2 {
        margin: 0;
        color: var(--text);
    }
    
    .controls {
        display: flex;
        gap: 0.5rem;
        align-items: center;
    }
    
    .controls select {
        padding: 0.5rem;
        border-radius: 4px;
        border: 1px solid var(--border);
        background: var(--bg-input);
        color: var(--text);
    }
    
    .overview-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    
    .stat {
        text-align: center;
        padding: 0.5rem;
    }
    
    .stat .label {
        display: block;
        font-size: 0.85rem;
        color: var(--text-muted);
        margin-bottom: 0.25rem;
    }
    
    .stat .value {
        display: block;
        font-size: 1.5rem;
        font-weight: bold;
        color: var(--text);
    }
    
    .stat.error .value {
        color: var(--danger);
    }
    
    .stat.clickable {
        cursor: pointer;
        border-radius: 4px;
    }
    
    .stat.clickable:hover {
        background: var(--table-row-hover);
    }
    
    .filters {
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1rem;
        flex-wrap: wrap;
    }
    
    .filters input, .filters select {
        padding: 0.5rem;
        border-radius: 4px;
        border: 1px solid var(--border);
        background: var(--bg-input);
        color: var(--text);
    }
    
    .filters input::placeholder {
        color: var(--text-muted2);
    }
    
    .filters input[type="text"] {
        min-width: 200px;
    }
    
    .filters input[type="number"] {
        width: 100px;
    }
    
    .table-container {
        overflow-x: auto;
    }
    
    table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.9rem;
    }
    
    th, td {
        padding: 0.5rem;
        text-align: left;
        border-bottom: 1px solid var(--border);
        color: var(--text);
    }
    
    th {
        background: var(--table-header-bg);
        font-weight: 600;
        color: var(--text-muted);
    }
    
    tr:hover {
        background: var(--table-row-hover);
    }
    
    tr.error {
        background: rgba(255, 77, 94, 0.1);
    }
    
    tr.warning {
        background: rgba(245, 158, 11, 0.1);
    }
    
    .time {
        font-family: monospace;
        font-size: 0.85rem;
        color: var(--text-muted);
    }
    
    .path {
        font-family: monospace;
        font-size: 0.85rem;
        max-width: 250px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--text);
    }
    
    .method {
        display: inline-block;
        padding: 0.15rem 0.4rem;
        border-radius: 3px;
        font-size: 0.75rem;
        font-weight: bold;
        text-transform: uppercase;
    }
    
    .method.get { background: rgba(45, 125, 255, 0.2); color: #5aa3ff; }
    .method.post { background: rgba(54, 211, 124, 0.2); color: var(--success); }
    .method.put { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
    .method.delete { background: rgba(255, 77, 94, 0.2); color: var(--danger); }
    .method.patch { background: rgba(167, 139, 250, 0.2); color: #a78bfa; }
    
    .status {
        display: inline-block;
        padding: 0.15rem 0.4rem;
        border-radius: 3px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    
    .status-green { background: rgba(54, 211, 124, 0.2); color: var(--success); }
    .status-blue { background: rgba(45, 125, 255, 0.2); color: #5aa3ff; }
    .status-yellow { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
    .status-red { background: rgba(255, 77, 94, 0.2); color: var(--danger); }
    .status-gray { background: var(--bg-input); color: var(--text-muted); }
    
    .slow {
        color: var(--warning);
        font-weight: bold;
    }
    
    .empty {
        text-align: center;
        color: var(--text-muted2);
        padding: 2rem !important;
    }
    
    .mini-table {
        font-size: 0.85rem;
    }
    
    .mini-table th, .mini-table td {
        padding: 0.35rem 0.5rem;
    }
    
    /* Trace Detail Modal */
    .trace-detail {
        font-size: 0.9rem;
        color: var(--text);
    }
    
    .trace-header {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding: 1rem;
        background: var(--panel-bg);
        border: 1px solid var(--border);
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    
    .trace-header .path {
        flex: 1;
        color: var(--text);
    }
    
    .trace-header .duration {
        font-weight: bold;
        font-size: 1.1rem;
        color: var(--text);
    }
    
    .error-box {
        background: rgba(255, 77, 94, 0.15);
        color: var(--danger);
        padding: 0.75rem;
        border-radius: 4px;
        margin-bottom: 1rem;
        border: 1px solid rgba(255, 77, 94, 0.3);
    }
    
    .trace-meta {
        display: flex;
        gap: 1.5rem;
        font-size: 0.85rem;
        color: var(--text-muted);
        margin-bottom: 1rem;
    }
    
    .trace-meta code {
        background: var(--bg-input);
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-size: 0.8rem;
        color: var(--text);
    }
    
    h3 {
        color: var(--text);
    }
    
    h4 {
        margin: 1rem 0 0.5rem;
        font-size: 0.95rem;
        color: var(--text);
    }
    
    .spans-timeline {
        background: var(--panel-bg);
        border: 1px solid var(--border);
        border-radius: 4px;
        padding: 0.5rem;
    }
    
    .span-row {
        display: flex;
        align-items: center;
        padding: 0.25rem 0;
        gap: 0.5rem;
    }
    
    .span-row.child {
        padding-left: 1.5rem;
        font-size: 0.85rem;
    }
    
    .span-name {
        width: 250px;
        font-family: monospace;
        font-size: 0.8rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--text-muted);
    }
    
    .span-bar-container {
        flex: 1;
        height: 20px;
        background: var(--bg-input);
        border-radius: 3px;
        position: relative;
    }
    
    .span-bar {
        height: 100%;
        background: var(--success);
        border-radius: 3px;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding-right: 0.25rem;
        font-size: 0.7rem;
        color: white;
        min-width: 40px;
    }
    
    .span-bar.error {
        background: var(--danger);
    }
    
    .span-bar.child-bar {
        background: rgba(54, 211, 124, 0.7);
    }
    
    .spans-details {
        margin-top: 0.5rem;
    }
    
    details {
        margin-bottom: 0.5rem;
        border: 1px solid var(--border);
        border-radius: 4px;
        background: var(--bg-card);
    }
    
    summary {
        padding: 0.5rem;
        cursor: pointer;
        background: var(--panel-bg);
        color: var(--text);
    }
    
    summary:hover {
        background: var(--table-row-hover);
    }
    
    .span-kind {
        display: inline-block;
        background: rgba(45, 125, 255, 0.2);
        color: #5aa3ff;
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-size: 0.7rem;
        margin-right: 0.5rem;
    }
    
    .error-badge {
        background: rgba(255, 77, 94, 0.2);
        color: var(--danger);
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-size: 0.7rem;
        margin-left: 0.5rem;
    }
    
    .span-attrs {
        padding: 0.5rem;
        font-family: monospace;
        font-size: 0.8rem;
        background: var(--bg-card);
    }
    
    .attr {
        margin-bottom: 0.25rem;
    }
    
    .attr .key {
        color: var(--text-muted);
    }
    
    .attr .value {
        color: var(--text);
    }
    
    .attr.error .value {
        color: var(--danger);
    }
    
    .service-badge {
        background: rgba(109, 92, 255, 0.2);
        color: var(--primary);
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 500;
        margin-right: 0.5rem;
    }
    
    td.service {
        font-size: 0.8rem;
        color: var(--text-muted);
    }
    
    /* Tabs */
    .tabs {
        display: flex;
        gap: 0.25rem;
        background: var(--bg-input);
        padding: 0.25rem;
        border-radius: 8px;
    }
    
    .tab {
        padding: 0.5rem 1rem;
        border: none;
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        border-radius: 6px;
        font-size: 0.9rem;
        transition: all 0.2s;
    }
    
    .tab:hover {
        color: var(--text);
        background: var(--panel-bg);
    }
    
    .tab.active {
        background: var(--primary);
        color: white;
    }
    
    /* Controls input */
    .controls input[type="text"] {
        padding: 0.5rem 0.75rem;
        border-radius: 4px;
        border: 1px solid var(--border);
        background: var(--bg-input);
        color: var(--text);
        min-width: 150px;
    }
    
    .controls input[type="text"]::placeholder {
        color: var(--text-muted);
    }
    
    /* Logs Section */
    .logs-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }
    
    .logs-header h3 {
        margin: 0;
        color: var(--text);
    }
    
    .log-count {
        font-size: 0.85rem;
        color: var(--text-muted);
        background: var(--bg-input);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
    }
    
    .loading-logs {
        text-align: center;
        padding: 2rem;
        color: var(--text-muted);
    }
    
    .empty-logs {
        text-align: center;
        padding: 2rem;
        color: var(--text-muted);
    }
    
    .empty-logs .hint {
        font-size: 0.85rem;
        margin-top: 0.5rem;
        opacity: 0.7;
    }
    
    .logs-container {
        max-height: 600px;
        overflow-y: auto;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: 0.8rem;
        background: var(--bg-input);
        border-radius: 8px;
        padding: 0.5rem;
    }
    
    .log-entry {
        display: flex;
        gap: 0.5rem;
        padding: 0.35rem 0.5rem;
        border-radius: 4px;
        line-height: 1.4;
        flex-wrap: wrap;
        align-items: baseline;
    }
    
    .log-entry:hover {
        background: var(--panel-bg);
    }
    
    .log-entry.error {
        background: rgba(244, 67, 54, 0.1);
    }
    
    .log-entry.warning {
        background: rgba(255, 152, 0, 0.1);
    }
    
    .log-time {
        color: var(--text-muted);
        flex-shrink: 0;
        font-size: 0.75rem;
    }
    
    .log-level {
        font-weight: 600;
        flex-shrink: 0;
        min-width: 70px;
    }
    
    .log-logger {
        color: var(--primary);
        flex-shrink: 0;
        max-width: 150px;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    .log-message {
        color: var(--text);
        flex: 1;
        word-break: break-word;
    }
    
    .log-location {
        color: var(--text-muted);
        font-size: 0.7rem;
        flex-shrink: 0;
    }
    
    /* Database Tab */
    .db-section {
        padding: 1rem;
    }
    
    .db-section h3 {
        margin: 0 0 0.5rem 0;
    }
    
    .db-warning {
        color: var(--warning, #ff9800);
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    
    .loading-db {
        text-align: center;
        padding: 2rem;
        color: var(--text-muted);
    }
    
    .db-info {
        background: var(--bg-input);
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1.5rem;
    }
    
    .db-info-row {
        display: flex;
        gap: 1rem;
        padding: 0.5rem 0;
        border-bottom: 1px solid var(--border);
    }
    
    .db-info-row:last-child {
        border-bottom: none;
    }
    
    .db-info-row .label {
        color: var(--text-muted);
        min-width: 80px;
    }
    
    .db-info-row code {
        font-family: monospace;
        font-size: 0.85rem;
        color: var(--primary);
    }
    
    .status-badge {
        color: var(--danger, #f44336);
    }
    
    .status-badge.exists {
        color: var(--success, #4caf50);
    }
    
    .db-actions {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 2rem;
        margin-bottom: 1.5rem;
    }
    
    .action-group {
        background: var(--panel-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem;
    }
    
    .action-group h4 {
        margin: 0 0 0.5rem 0;
        color: var(--text);
    }
    
    .action-group p {
        font-size: 0.85rem;
        color: var(--text-muted);
        margin: 0 0 1rem 0;
    }
    
    .upload-controls {
        display: flex;
        gap: 0.5rem;
        align-items: center;
        flex-wrap: wrap;
    }
    
    .file-input {
        flex: 1;
        min-width: 200px;
        padding: 0.5rem;
        border: 1px solid var(--border);
        border-radius: 4px;
        background: var(--bg-input);
        color: var(--text);
    }
    
    .upload-warning {
        margin-top: 0.75rem !important;
        color: var(--danger, #f44336) !important;
        font-size: 0.8rem !important;
    }
    
    .db-footer {
        display: flex;
        justify-content: flex-end;
    }
</style>

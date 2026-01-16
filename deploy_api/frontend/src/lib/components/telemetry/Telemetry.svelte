<script>
    import { onMount } from 'svelte';
    import { api } from '../../api/client.js';
    import { toasts } from '../../stores/toast.js';
    import Card from '../ui/Card.svelte';
    import Button from '../ui/Button.svelte';
    import Modal from '../ui/Modal.svelte';
    
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
    });
</script>

<div class="telemetry">
    <div class="header">
        <h2>🔍 Telemetry Dashboard</h2>
        <div class="controls">
            <select bind:value={hours} on:change={refresh}>
                <option value={1}>Last 1 hour</option>
                <option value={6}>Last 6 hours</option>
                <option value={24}>Last 24 hours</option>
                <option value={168}>Last 7 days</option>
            </select>
            <Button on:click={refresh} disabled={loading}>
                {loading ? '⏳' : '🔄'} Refresh
            </Button>
        </div>
    </div>
    
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
</div>

<!-- Drill-down Modal -->
{#if showDrilldown && selectedTrace}
<Modal title="Request Detail" on:close={() => showDrilldown = false} width="800px">
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
    }
    
    .controls {
        display: flex;
        gap: 0.5rem;
        align-items: center;
    }
    
    .controls select {
        padding: 0.5rem;
        border-radius: 4px;
        border: 1px solid var(--border-color, #ddd);
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
        color: #666;
        margin-bottom: 0.25rem;
    }
    
    .stat .value {
        display: block;
        font-size: 1.5rem;
        font-weight: bold;
    }
    
    .stat.error .value {
        color: #dc3545;
    }
    
    .stat.clickable {
        cursor: pointer;
    }
    
    .stat.clickable:hover {
        background: #f5f5f5;
        border-radius: 4px;
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
        border: 1px solid var(--border-color, #ddd);
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
        border-bottom: 1px solid #eee;
    }
    
    th {
        background: #f9f9f9;
        font-weight: 600;
    }
    
    tr.error {
        background: #fff5f5;
    }
    
    tr.warning {
        background: #fffbeb;
    }
    
    .time {
        font-family: monospace;
        font-size: 0.85rem;
    }
    
    .path {
        font-family: monospace;
        font-size: 0.85rem;
        max-width: 250px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    .method {
        display: inline-block;
        padding: 0.15rem 0.4rem;
        border-radius: 3px;
        font-size: 0.75rem;
        font-weight: bold;
        text-transform: uppercase;
    }
    
    .method.get { background: #e3f2fd; color: #1565c0; }
    .method.post { background: #e8f5e9; color: #2e7d32; }
    .method.put { background: #fff3e0; color: #ef6c00; }
    .method.delete { background: #ffebee; color: #c62828; }
    .method.patch { background: #f3e5f5; color: #7b1fa2; }
    
    .status {
        display: inline-block;
        padding: 0.15rem 0.4rem;
        border-radius: 3px;
        font-size: 0.8rem;
        font-weight: bold;
    }
    
    .status-green { background: #e8f5e9; color: #2e7d32; }
    .status-blue { background: #e3f2fd; color: #1565c0; }
    .status-yellow { background: #fff3e0; color: #ef6c00; }
    .status-red { background: #ffebee; color: #c62828; }
    .status-gray { background: #f5f5f5; color: #666; }
    
    .slow {
        color: #ef6c00;
        font-weight: bold;
    }
    
    .empty {
        text-align: center;
        color: #999;
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
    }
    
    .trace-header {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding: 1rem;
        background: #f9f9f9;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    
    .trace-header .path {
        flex: 1;
    }
    
    .trace-header .duration {
        font-weight: bold;
        font-size: 1.1rem;
    }
    
    .error-box {
        background: #ffebee;
        color: #c62828;
        padding: 0.75rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    
    .trace-meta {
        display: flex;
        gap: 1.5rem;
        font-size: 0.85rem;
        color: #666;
        margin-bottom: 1rem;
    }
    
    .trace-meta code {
        background: #f5f5f5;
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-size: 0.8rem;
    }
    
    h4 {
        margin: 1rem 0 0.5rem;
        font-size: 0.95rem;
    }
    
    .spans-timeline {
        background: #f9f9f9;
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
    }
    
    .span-bar-container {
        flex: 1;
        height: 20px;
        background: #eee;
        border-radius: 3px;
        position: relative;
    }
    
    .span-bar {
        height: 100%;
        background: #4caf50;
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
        background: #f44336;
    }
    
    .span-bar.child-bar {
        background: #81c784;
    }
    
    .spans-details {
        margin-top: 0.5rem;
    }
    
    details {
        margin-bottom: 0.5rem;
        border: 1px solid #eee;
        border-radius: 4px;
    }
    
    summary {
        padding: 0.5rem;
        cursor: pointer;
        background: #f9f9f9;
    }
    
    summary:hover {
        background: #f0f0f0;
    }
    
    .span-kind {
        display: inline-block;
        background: #e3f2fd;
        color: #1565c0;
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-size: 0.7rem;
        margin-right: 0.5rem;
    }
    
    .error-badge {
        background: #ffebee;
        color: #c62828;
        padding: 0.1rem 0.3rem;
        border-radius: 3px;
        font-size: 0.7rem;
        margin-left: 0.5rem;
    }
    
    .span-attrs {
        padding: 0.5rem;
        font-family: monospace;
        font-size: 0.8rem;
    }
    
    .attr {
        margin-bottom: 0.25rem;
    }
    
    .attr .key {
        color: #666;
    }
    
    .attr .value {
        color: #333;
    }
    
    .attr.error .value {
        color: #c62828;
    }
    
    .service-badge {
        background: #e3f2fd;
        color: #1565c0;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 500;
        margin-right: 0.5rem;
    }
    
    td.service {
        font-size: 0.8rem;
        color: #666;
    }
</style>

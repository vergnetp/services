<script>
  import { onMount } from 'svelte'
  import { servers, snapshots, serversStore, snapshotsStore } from '../../stores/app.js'
  import { toasts } from '../../stores/toast.js'
  import { api, apiStreamMultipart, getDoToken, getCfToken } from '../../api/client.js'
  import { auth } from '../../stores/auth.js'
  import Card from '../ui/Card.svelte'
  import Button from '../ui/Button.svelte'
  import Badge from '../ui/Badge.svelte'
  import Modal from '../ui/Modal.svelte'
  
  // Form state
  let name = ''
  let project = ''
  let environment = 'prod'
  let tags = ''
  let sourceType = 'code'  // code, git, image, image_file
  let port = 8000
  let envVars = ''
  
  // Git source
  let gitUrl = ''
  let gitBranch = 'main'
  let gitToken = ''
  let gitFolders = []  // [{path, isMain}]
  let gitFolderInput = ''
  
  // Image source (registry)
  let imageUrl = ''
  let selectedServer = ''
  
  // Image file source (local docker tar)
  let imageFile = null
  let imageName = ''
  let containerPort = ''
  let hostPort = ''
  
  // Local code - Build folders (main + dependencies)
  let buildFolders = []  // [{name, fileContents, isMain, fileCount}]
  let pendingCodeFile = null
  let folderPickerRef = null
  let pendingFolderCallback = null
  let rememberFolders = true
  let isDraggingFolder = false
  
  // Dockerfile
  let dockerfile = ''
  let dockerfileSource = ''  // 'from folder', 'generated', 'multi-folder'
  let showDockerfilePreview = false
  let dockerfileQuickFrom = ''
  let dockerfileQuickCmd = ''
  
  // Server provisioning
  let selectedSnapshot = ''
  let selectedRegion = 'lon1'
  let selectedSize = 's-1vcpu-2gb'
  let regions = []
  let sizes = []
  
  // Filter servers by selected region (with safe default)
  let filteredServers = []
  $: filteredServers = ($servers || []).filter(s => !selectedRegion || s.region === selectedRegion)
  
  // Deployment state
  let deploying = false
  let progress = 0
  let logs = []
  let selectedServers = new Set()
  let additionalServers = 0
  let deployResult = null  // Result from last deployment
  
  // Cleanup confirmation state
  let showCleanupConfirm = false
  let cleanupServers = []  // Servers that will have containers stopped
  let pendingDeployAction = null  // Function to call after confirmation
  
  // Service config
  let autoEnv = true
  let persistData = true
  let dependencies = {
    postgres: false,
    redis: false,
    mysql: false,
    mongo: false
  }
  
  // Domain setup
  let setupDomain = true
  let baseDomain = 'digitalpixo.com'
  let domainAliases = ''
  $: domainPreview = name && project && environment ? `${name}-${project}-${environment}.${baseDomain}` : ''
  
  // Deploy config management
  let configStatus = ''
  let showExcludePatterns = false
  let excludePatterns = [
    'node_modules/',
    '__pycache__/',
    '*.pyc',
    '.git/',
    '.venv/',
    'venv/',
    '.env',
    '.DS_Store',
    '.idea/',
    '.vscode/',
    'dist/',
    'build/',
    '.pytest_cache/',
    '.mypy_cache/',
  ]
  let excludePatternsText = excludePatterns.join('\n')
  
  // Collapsible sections (collapsed by default for advanced options)
  let showEnvVars = false
  let showServiceConfig = false
  let showProvisioning = false
  
  const DEFAULT_EXCLUDE_PATTERNS = [...excludePatterns]
  const environments = ['dev', 'test', 'staging', 'uat', 'prod']
  
  onMount(() => {
    // Use SWR stores (serversStore/snapshotsStore) so we don't mutate derived stores.
    // This fixes "servers.set is not a function" and ensures consistent refresh behavior.
    serversStore.refresh().catch(() => {})
    snapshotsStore.refresh().catch(() => {})
    loadRegionsAndSizes()
  })
  
  // Auto-load config when project/service/env changes
  $: if (name && project) {
    loadDeployConfigSilent()
  }
  
  // Auto-select base snapshot when snapshots become available
  $: if ($snapshots?.length > 0 && !selectedSnapshot) {
    // Prefer snapshots with "base" in the name, otherwise first one
    const baseSnapshot = $snapshots.find(s => 
      (s.name || '').toLowerCase().includes('base')
    )
    selectedSnapshot = baseSnapshot?.id || baseSnapshot?.name || $snapshots[0].id || $snapshots[0].name
  }
  
  async function loadRegionsAndSizes() {
    try {
      // Load regions
      try {
        const regData = await api('GET', '/infra/regions')
        regions = regData.regions || regData || []
      } catch (e) {
        // Fallback defaults
        regions = [
          { slug: 'nyc1', name: 'New York 1' },
          { slug: 'nyc3', name: 'New York 3' },
          { slug: 'sfo3', name: 'San Francisco 3' },
          { slug: 'ams3', name: 'Amsterdam 3' },
          { slug: 'sgp1', name: 'Singapore 1' },
          { slug: 'lon1', name: 'London 1' },
          { slug: 'fra1', name: 'Frankfurt 1' },
        ]
      }
      
      // Load sizes  
      try {
        const sizeData = await api('GET', '/infra/sizes')
        sizes = sizeData.sizes || sizeData || []
      } catch (e) {
        // Fallback defaults
        sizes = [
          { slug: 's-1vcpu-512mb-10gb', description: '512MB / 1 vCPU' },
          { slug: 's-1vcpu-1gb', description: '1GB / 1 vCPU' },
          { slug: 's-1vcpu-2gb', description: '2GB / 1 vCPU' },
          { slug: 's-2vcpu-2gb', description: '2GB / 2 vCPU' },
          { slug: 's-2vcpu-4gb', description: '4GB / 2 vCPU' },
          { slug: 's-4vcpu-8gb', description: '8GB / 4 vCPU' },
        ]
      }
    } catch (err) {
      console.error('Failed to load regions/sizes:', err)
    }
  }
  
  async function loadDeployConfig() {
    if (!name) {
      toasts.warning('Enter app name first')
      return
    }
    
    configStatus = 'Loading...'
    try {
      const proj = project || 'default'
      const response = await api('GET', `/infra/deploy-configs/${proj}/${name}/${environment}`)
      applyConfig(response)
      configStatus = '✓ Loaded'
      toasts.success('Config loaded')
    } catch (err) {
      if (err.message?.includes('404')) {
        configStatus = 'No saved config'
        toasts.info('No saved config found')
      } else {
        configStatus = 'Load failed'
        toasts.error('Failed to load config')
      }
    }
  }
  
  async function loadDeployConfigSilent() {
    try {
      const proj = project || 'default'
      const response = await api('GET', `/infra/deploy-configs/${proj}/${name}/${environment}`)
      applyConfig(response)
      configStatus = '✓ Auto-loaded'
    } catch (err) {
      // Silent fail - no saved config
      configStatus = ''
    }
  }
  
  function applyConfig(config) {
    if (config.source_type) {
      const sourceMap = { 'folder': 'code', 'git': 'git', 'image': 'image' }
      sourceType = sourceMap[config.source_type] || config.source_type
    }
    if (config.git_url) gitUrl = config.git_url
    if (config.git_branch) gitBranch = config.git_branch
    if (config.port) port = config.port
    if (config.env_vars && Object.keys(config.env_vars).length > 0) {
      envVars = Object.entries(config.env_vars).map(([k, v]) => `${k}=${v}`).join('\n')
    }
    if (config.exclude_patterns?.length > 0) {
      excludePatterns = config.exclude_patterns
      excludePatternsText = excludePatterns.join('\n')
    }
    if (config.server_ips?.length > 0) {
      selectedServers = new Set(config.server_ips)
    }
  }
  
  async function saveDeployConfig() {
    if (!name) {
      toasts.warning('Enter app name first')
      return
    }
    
    configStatus = 'Saving...'
    
    // Parse env vars
    const envVarsObj = {}
    for (const line of envVars.split('\n')) {
      const trimmed = line.trim()
      if (trimmed && trimmed.includes('=')) {
        const [key, ...rest] = trimmed.split('=')
        envVarsObj[key.trim()] = rest.join('=').trim()
      }
    }
    
    // Parse exclude patterns
    const patterns = excludePatternsText.split('\n').map(s => s.trim()).filter(Boolean)
    
    const config = {
      project_name: project || 'default',
      service_name: name,
      env: environment,
      source_type: sourceType === 'code' ? 'folder' : sourceType,
      git_url: gitUrl || null,
      git_branch: gitBranch || 'main',
      exclude_patterns: patterns.length > 0 ? patterns : DEFAULT_EXCLUDE_PATTERNS,
      port: port,
      env_vars: envVarsObj,
      server_ips: Array.from(selectedServers),
    }
    
    try {
      await api('POST', '/infra/deploy-configs', config)
      configStatus = '✓ Saved'
      toasts.success('Config saved')
    } catch (err) {
      configStatus = 'Save failed'
      toasts.error('Failed to save config')
    }
  }
  
  function toggleExcludePatterns() {
    showExcludePatterns = !showExcludePatterns
    if (!showExcludePatterns) {
      // Update patterns when closing
      excludePatterns = excludePatternsText.split('\n').map(s => s.trim()).filter(Boolean)
    }
  }
  
  function resetExcludePatterns() {
    excludePatterns = [...DEFAULT_EXCLUDE_PATTERNS]
    excludePatternsText = DEFAULT_EXCLUDE_PATTERNS.join('\n')
    toasts.info('Reset to default patterns')
  }
  
  function shouldIgnoreFile(filePath) {
    for (const pattern of excludePatterns) {
      // Handle directory patterns (ending with /)
      if (pattern.endsWith('/')) {
        const dirName = pattern.slice(0, -1)
        if (filePath.startsWith(dirName + '/') || filePath.includes('/' + dirName + '/')) {
          return true
        }
      }
      // Handle wildcard patterns (*.ext)
      else if (pattern.startsWith('*')) {
        const ext = pattern.slice(1)
        if (filePath.endsWith(ext)) {
          return true
        }
      }
      // Handle exact matches
      else if (filePath === pattern || filePath.endsWith('/' + pattern)) {
        return true
      }
    }
    return false
  }

  function toggleServer(ip) {
    if (selectedServers.has(ip)) {
      selectedServers.delete(ip)
    } else {
      selectedServers.add(ip)
    }
    selectedServers = selectedServers // trigger reactivity
  }
  
  function selectAllServers(select) {
    if (select) {
      // Only select servers in the current region filter
      (filteredServers || []).forEach(s => {
        const ip = s.ip || s.networks?.v4?.[0]?.ip_address
        if (ip) selectedServers.add(ip)
      })
    } else {
      selectedServers.clear()
    }
    selectedServers = selectedServers
  }
  
  // =============================================================================
  // Build Folders (Local Code)
  // =============================================================================
  
  function addBuildFolderUI() {
    // Trigger hidden folder picker - will call onFolderPicked when user selects
    pendingFolderCallback = async (files, folderName) => {
      await processSelectedFolder(files, folderName, buildFolders.length === 0)
    }
    folderPickerRef?.click()
  }
  
  async function onFolderPicked(event) {
    const files = Array.from(event.target.files || [])
    if (!files.length || !pendingFolderCallback) return
    
    // Debug: log all files received from browser
    console.log(`[Deploy] Browser returned ${files.length} files`)
    if (files.length < 50) {
      console.log('[Deploy] Files:', files.map(f => f.webkitRelativePath))
    } else {
      console.log('[Deploy] First 20 files:', files.slice(0, 20).map(f => f.webkitRelativePath))
    }
    
    // Get folder name from first file's path
    const firstPath = files[0].webkitRelativePath
    const folderName = firstPath.split('/')[0]
    
    await pendingFolderCallback(files, folderName)
    pendingFolderCallback = null
    
    // Reset input for reuse
    event.target.value = ''
  }
  
  // Drag & drop handlers for folder upload (no browser confirmation popup!)
  function handleDragEnter(e) {
    e.preventDefault()
    e.stopPropagation()
    isDraggingFolder = true
  }
  
  function handleDragLeave(e) {
    e.preventDefault()
    e.stopPropagation()
    if (!e.currentTarget.contains(e.relatedTarget)) {
      isDraggingFolder = false
    }
  }
  
  function handleDragOver(e) {
    e.preventDefault()
    e.stopPropagation()
  }
  
  async function handleDrop(e) {
    e.preventDefault()
    e.stopPropagation()
    isDraggingFolder = false
    
    const items = e.dataTransfer?.items
    if (!items || items.length === 0) return
    
    for (const item of items) {
      if (item.kind === 'file') {
        const entry = item.webkitGetAsEntry?.()
        if (entry?.isDirectory) {
          await processDroppedFolder(entry)
        }
      }
    }
  }
  
  async function processDroppedFolder(dirEntry) {
    const folderName = dirEntry.name
    
    if (buildFolders.some(f => f.name === folderName)) {
      toasts.error(`Folder "${folderName}" is already added`)
      return
    }
    
    toasts.info(`Reading ${folderName}/...`)
    const files = await readDirectoryRecursively(dirEntry, '')
    
    if (files.length === 0) {
      toasts.error(`No files found in ${folderName}/`)
      return
    }
    
    const isMain = buildFolders.length === 0
    await processDroppedFiles(files, folderName, isMain)
  }
  
  async function readDirectoryRecursively(dirEntry, basePath) {
    const files = []
    const reader = dirEntry.createReader()
    
    let entries = []
    let batch
    do {
      batch = await new Promise((resolve, reject) => {
        reader.readEntries(resolve, reject)
      })
      entries = entries.concat(batch)
    } while (batch.length > 0)
    
    for (const entry of entries) {
      const path = basePath ? `${basePath}/${entry.name}` : entry.name
      
      if (entry.isFile) {
        const file = await new Promise((resolve, reject) => {
          entry.file(resolve, reject)
        })
        file._relativePath = path
        files.push(file)
      } else if (entry.isDirectory) {
        const subFiles = await readDirectoryRecursively(entry, path)
        files.push(...subFiles)
      }
    }
    
    return files
  }
  
  async function processDroppedFiles(files, folderName, isMain) {
    if (isMain && buildFolders.some(f => f.isMain)) {
      buildFolders = buildFolders.map(f => ({...f, isMain: false}))
    }
    
    const fileContents = []
    let existingDockerfile = null
    let skippedCount = 0
    
    for (const file of files) {
      const relativePath = file._relativePath || file.name
      
      if (shouldIgnoreFile(relativePath)) {
        skippedCount++
        continue
      }
      
      const content = await readFileAsArrayBuffer(file)
      fileContents.push({ path: relativePath, content })
      
      if (isMain && relativePath === 'Dockerfile') {
        existingDockerfile = await readFileAsText(file)
      }
    }
    
    console.log(`[Deploy] Dropped ${folderName}/: ${files.length} total, ${skippedCount} skipped, ${fileContents.length} included`)
    
    buildFolders = [...buildFolders, {
      name: folderName,
      fileContents,
      isMain,
      fileCount: fileContents.length
    }]
    
    updateCodeSelectionInfo()
    
    if (buildFolders.some(f => f.isMain)) {
      updateDockerfilePreview(existingDockerfile)
    }
    
    if (rememberFolders && project && name) {
      saveFolderConfig()
    }
    
    toasts.success(`Added ${folderName}/ (${fileContents.length} files)`)
  }
  
  async function processSelectedFolder(files, folderName, isMain) {
    // Check if folder already added
    if (buildFolders.some(f => f.name === folderName)) {
      toasts.error(`Folder "${folderName}" is already added`)
      return
    }
    
    // If setting as main, clear existing main
    if (isMain && buildFolders.some(f => f.isMain)) {
      buildFolders = buildFolders.map(f => ({...f, isMain: false}))
    }
    
    // Read file contents
    const fileContents = []
    let existingDockerfile = null
    let skippedCount = 0
    
    for (const file of files) {
      const relativePath = file.webkitRelativePath.replace(`${folderName}/`, '')
      
      // Skip excluded patterns
      if (shouldIgnoreFile(relativePath)) {
        skippedCount++
        continue
      }
      
      // Read file content
      const content = await readFileAsArrayBuffer(file)
      fileContents.push({ path: relativePath, content })
      
      // Check for Dockerfile in main folder
      if (isMain && relativePath === 'Dockerfile') {
        existingDockerfile = await readFileAsText(file)
      }
    }
    
    console.log(`[Deploy] Processed ${folderName}/: ${files.length} total, ${skippedCount} skipped, ${fileContents.length} included`)
    
    buildFolders = [...buildFolders, {
      name: folderName,
      fileContents,
      isMain,
      fileCount: fileContents.length
    }]
    
    updateCodeSelectionInfo()
    
    // Update dockerfile preview
    if (buildFolders.some(f => f.isMain)) {
      updateDockerfilePreview(existingDockerfile)
    }
    
    // Save folder config
    if (rememberFolders && project && name) {
      saveFolderConfig()
    }
    
    toasts.success(`Added ${folderName}/ (${fileContents.length} files)`)
  }
  
  function readFileAsArrayBuffer(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(new Uint8Array(reader.result))
      reader.onerror = reject
      reader.readAsArrayBuffer(file)
    })
  }
  
  function readFileAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = reject
      reader.readAsText(file)
    })
  }
  
  function removeBuildFolder(index) {
    buildFolders = buildFolders.filter((_, i) => i !== index)
    updateCodeSelectionInfo()
    if (buildFolders.length > 0 && !buildFolders.some(f => f.isMain)) {
      // Make first folder the main
      buildFolders = buildFolders.map((f, i) => ({...f, isMain: i === 0}))
    }
  }
  
  function setFolderAsMain(index) {
    buildFolders = buildFolders.map((f, i) => ({...f, isMain: i === index}))
    updateDockerfilePreview()
  }
  
  function updateCodeSelectionInfo() {
    const hasMain = buildFolders.some(f => f.isMain)
    if (!buildFolders.length) {
      pendingCodeFile = null
    } else if (hasMain) {
      // Create pending zip
      createPendingZip()
    }
  }
  
  async function createPendingZip() {
    if (!buildFolders.length) return
    
    // Dynamic import JSZip
    const { default: JSZip } = await import('https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm')
    const zip = new JSZip()
    
    // Add all folders side by side
    for (const folder of buildFolders) {
      for (const { path, content } of folder.fileContents) {
        zip.file(`${folder.name}/${path}`, content)
      }
    }
    
    // Add dockerfile at root if multi-folder
    if (buildFolders.length > 1 && dockerfile) {
      zip.file('Dockerfile', dockerfile)
    }
    
    pendingCodeFile = await zip.generateAsync({ type: 'blob' })
  }
  
  function updateDockerfilePreview(existingDockerfile = null) {
    showDockerfilePreview = true
    
    if (existingDockerfile) {
      dockerfile = existingDockerfile
      dockerfileSource = 'from folder'
    } else if (buildFolders.length > 1) {
      dockerfile = generateMultiFolderDockerfile()
      dockerfileSource = 'multi-folder'
    } else if (buildFolders.length === 1) {
      const mainFolder = buildFolders[0]
      dockerfile = generateDockerfileTemplate(mainFolder.fileContents.map(f => f.path))
      dockerfileSource = 'generated'
    }
    
    parseDockerfileQuickFields()
  }
  
  function generateMultiFolderDockerfile() {
    const mainFolder = buildFolders.find(f => f.isMain)
    if (!mainFolder) return ''
    
    const deps = buildFolders.filter(f => !f.isMain)
    const hasRequirements = mainFolder.fileContents.some(f => f.path === 'requirements.txt')
    const hasPackageJson = mainFolder.fileContents.some(f => f.path === 'package.json')
    
    let df = `FROM python:3.11-slim\n\nWORKDIR /app\n\n`
    
    // Copy dependencies first
    for (const dep of deps) {
      df += `# Copy ${dep.name}\nCOPY ${dep.name}/ ./${dep.name}/\n\n`
    }
    
    // Copy main folder
    df += `# Copy main service\nCOPY ${mainFolder.name}/ ./${mainFolder.name}/\n\n`
    
    if (hasRequirements) {
      df += `# Install dependencies\nRUN pip install --no-cache-dir -r ${mainFolder.name}/requirements.txt\n\n`
    }
    
    // Stay at /app so sibling folder imports work
    df += `EXPOSE ${port}\n\n`
    df += `CMD ["uvicorn", "${mainFolder.name}.main:app", "--host", "0.0.0.0", "--port", "${port}"]\n`
    
    return df
  }
  
  function generateDockerfileTemplate(fileList) {
    const hasRequirements = fileList.includes('requirements.txt')
    const hasPackageJson = fileList.includes('package.json')
    const hasPyprojectToml = fileList.includes('pyproject.toml')
    
    if (hasRequirements || hasPyprojectToml) {
      return `FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE ${port}

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${port}"]
`
    } else if (hasPackageJson) {
      return `FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE ${port}

CMD ["node", "index.js"]
`
    } else {
      return `FROM python:3.11-slim

WORKDIR /app

COPY . .

EXPOSE ${port}

CMD ["python", "main.py"]
`
    }
  }
  
  function parseDockerfileQuickFields() {
    const fromMatch = dockerfile.match(/^FROM\s+(\S+)/m)
    const cmdMatch = dockerfile.match(/^CMD\s+(.+)$/m)
    
    dockerfileQuickFrom = fromMatch ? fromMatch[1] : ''
    dockerfileQuickCmd = cmdMatch ? cmdMatch[1] : ''
  }
  
  function updateDockerfileField(field) {
    if (field === 'from' && dockerfileQuickFrom) {
      dockerfile = dockerfile.replace(/^FROM\s+\S+/m, `FROM ${dockerfileQuickFrom}`)
    } else if (field === 'cmd' && dockerfileQuickCmd) {
      if (dockerfile.includes('CMD ')) {
        dockerfile = dockerfile.replace(/^CMD\s+.+$/m, `CMD ${dockerfileQuickCmd}`)
      } else {
        dockerfile += `\nCMD ${dockerfileQuickCmd}\n`
      }
    }
    dockerfileSource = 'edited'
  }
  
  function saveFolderConfig() {
    if (!project || !name) return
    const key = `build_folders_${project}_${name}`
    const config = buildFolders.map(f => ({ name: f.name, isMain: f.isMain }))
    localStorage.setItem(key, JSON.stringify(config))
  }
  
  function loadSavedFolderConfig() {
    if (!project || !name) return null
    const key = `build_folders_${project}_${name}`
    const saved = localStorage.getItem(key)
    return saved ? JSON.parse(saved) : null
  }
  
  // =============================================================================
  // Git Folders
  // =============================================================================
  
  function addGitFolder(isMain) {
    if (!gitFolderInput.trim()) {
      toasts.error('Please enter a folder path')
      return
    }
    
    const path = gitFolderInput.trim()
    
    // If setting as main, clear existing main
    if (isMain && gitFolders.some(f => f.isMain)) {
      gitFolders = gitFolders.map(f => ({...f, isMain: false}))
    }
    
    // Check duplicate
    if (gitFolders.some(f => f.path === path)) {
      toasts.error('This folder is already added')
      return
    }
    
    gitFolders = [...gitFolders, { path, isMain }]
    gitFolderInput = ''
  }
  
  function removeGitFolder(index) {
    gitFolders = gitFolders.filter((_, i) => i !== index)
  }
  
  // =============================================================================
  // Image File Upload
  // =============================================================================
  
  function handleImageFileSelect(event) {
    const file = event.target.files?.[0]
    if (file) {
      if (!file.name.endsWith('.tar') && !file.name.endsWith('.tar.gz')) {
        toasts.error('Only .tar or .tar.gz image files are supported')
        return
      }
      imageFile = file
      toasts.success(`Selected: ${file.name}`)
    }
  }
  
  // Convert URLs in text to clickable links
  function linkifyUrls(text) {
    const urlPattern = /(https?:\/\/[^\s]+)/g
    return text.replace(urlPattern, '<a href="$1" target="_blank" class="log-link">$1</a>')
  }
  
  function log(message, type = 'info') {
    logs = [...logs, { message, type, time: new Date() }]
  }
  
  async function startDeployment(e) {
    e.preventDefault()
    
    if (!name) {
      toasts.error('App name is required')
      return
    }
    
    if (sourceType === 'code' && !buildFolders.some(f => f.isMain)) {
      toasts.error('Add a main folder with your code')
      return
    }
    
    if (sourceType === 'git' && !gitUrl) {
      toasts.error('Git URL is required')
      return
    }
    
    if (sourceType === 'image' && !imageUrl) {
      toasts.error('Docker image URL is required')
      return
    }
    
    if (sourceType === 'image_file' && !imageFile) {
      toasts.error('Upload a Docker image file (.tar)')
      return
    }
    
    if (sourceType === 'image_file' && !imageName) {
      toasts.error('Image name is required for local images')
      return
    }
    
    if (selectedServers.size === 0 && additionalServers === 0) {
      toasts.error('Select at least one server or add new servers')
      return
    }
    
    if (additionalServers > 0 && !selectedSnapshot) {
      toasts.error('Select a snapshot for new servers')
      return
    }
    
    if (!getDoToken()) {
      toasts.error('Configure your DO Token in Settings first')
      return
    }
    
    if (setupDomain && !getCfToken()) {
      toasts.error('Configure your Cloudflare Token in Settings first (required for domain setup)')
      return
    }
    
    // Check for orphan servers (scale-down scenario)
    const targetServerIps = [...selectedServers]
    if (project && name && environment) {
      try {
        const params = new URLSearchParams({
          project,
          environment,
          service_name: name
        })
        const state = await api('GET', `/infra/services/state?${params}`)
        
        if (state.server_ips && state.server_ips.length > 0) {
          // Find servers that are currently running but not in target list
          const orphans = state.servers.filter(s => !targetServerIps.includes(s.ip))
          
          if (orphans.length > 0) {
            // Show confirmation modal
            cleanupServers = orphans
            pendingDeployAction = () => executeDeployment(e)
            showCleanupConfirm = true
            return
          }
        }
      } catch (err) {
        // Service doesn't exist yet or error - proceed without cleanup check
        console.log('Service state check:', err.message || err)
      }
    }
    
    // No orphans - proceed directly
    await executeDeployment(e)
  }
  
  async function confirmCleanupAndDeploy() {
    showCleanupConfirm = false
    
    // Get container name for cleanup
    const containerName = `${project}_${name}_${environment}`.replace(/[^a-zA-Z0-9_]/g, '_')
    
    // Cleanup orphan containers
    if (cleanupServers.length > 0) {
      const orphanIps = cleanupServers.map(s => s.ip)
      log(`Stopping containers on ${cleanupServers.length} server(s)...`)
      
      try {
        const result = await api('POST', `/infra/services/cleanup?do_token=${getDoToken()}`, {
          server_ips: orphanIps,
          container_name: containerName
        })
        log(`Cleanup complete: ${result.cleaned} stopped, ${result.failed} failed`)
      } catch (err) {
        log(`Cleanup warning: ${err.message || err}`, 'warning')
      }
    }
    
    cleanupServers = []
    
    // Now proceed with deployment
    if (pendingDeployAction) {
      await pendingDeployAction()
      pendingDeployAction = null
    }
  }
  
  async function executeDeployment(e) {
    deploying = true
    progress = 0
    logs = []
    deployResult = null  // Reset previous result
    
    try {
      log(`Starting deployment of ${name}...`)
      progress = 10
      
      // For code uploads, generate zip blob
      let codeBlob = null
      if (sourceType === 'code') {
        log('Creating code archive...')
        const { default: JSZip } = await import('https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm')
        const zip = new JSZip()
        
        // Add all folders side by side
        for (const folder of buildFolders) {
          for (const { path, content } of folder.fileContents) {
            zip.file(`${folder.name}/${path}`, content)
          }
        }
        
        // Add dockerfile at root if multi-folder
        if (buildFolders.length > 1 && dockerfile) {
          zip.file('Dockerfile', dockerfile)
        }
        
        codeBlob = await zip.generateAsync({ type: 'blob' })
      }
      
      log('Sending deployment request... server provisioning may take 30-60s')
      progress = 20
      
      // Build query params for multipart endpoint
      const doToken = getDoToken()
      const cfToken = getCfToken()
      const queryParams = new URLSearchParams({
        do_token: doToken,
        snapshot_id: selectedSnapshot || '',
        new_server_count: String(additionalServers),
        region: selectedRegion,
        size: selectedSize,
        project: project || '',
        environment: environment,
        setup_domain: String(setupDomain),
        base_domain: baseDomain,
        domain_aliases: JSON.stringify(domainAliases.split(',').map(d => d.trim()).filter(Boolean)),
      })
      // Add CF token if domain setup is enabled and token exists
      if (setupDomain && cfToken) {
        queryParams.set('cf_token', cfToken)
      }
      
      // Build FormData
      const formData = new FormData()
      formData.append('name', name)
      formData.append('port', String(port))
      formData.append('source_type', sourceType)
      formData.append('env_vars', envVars)
      formData.append('tags', tags)
      formData.append('server_ips', JSON.stringify(Array.from(selectedServers)))
      formData.append('depends_on', JSON.stringify(Object.entries(dependencies).filter(([_, v]) => v).map(([k]) => k)))
      formData.append('exclude_patterns', JSON.stringify(excludePatterns))
      
      if (dockerfile) formData.append('dockerfile', dockerfile)
      if (gitUrl) formData.append('git_url', gitUrl)
      if (gitBranch) formData.append('git_branch', gitBranch)
      if (gitToken) formData.append('git_token', gitToken)
      if (gitFolders.length) formData.append('git_folders', JSON.stringify(gitFolders))
      if (imageUrl) formData.append('image', imageUrl)
      if (codeBlob) formData.append('code_tar', codeBlob, 'code.zip')
      
      // For image_file source
      if (sourceType === 'image_file') {
        if (imageFile) formData.append('image_tar', imageFile)
        if (imageName) formData.append('image', imageName)
        if (containerPort) formData.append('container_port', String(containerPort))
        if (hostPort) formData.append('host_port', String(hostPort))
      }
      
      // Send multipart request with SSE response via client
      await apiStreamMultipart(`/infra/deploy/multipart?${queryParams}`, formData, (msg) => {
        if (msg.type === 'log') {
          log(msg.message)
        } else if (msg.type === 'progress') {
          progress = Math.min(20 + (msg.percent || 0) * 0.8, 95)
        } else if (msg.type === 'done') {
          deployResult = msg
          progress = 100
          // Check if deployment actually succeeded
          if (!msg.success) {
            const failedCount = msg.failed_count || 0
            const errorMsg = msg.error || `Deployment failed: ${failedCount} server(s) failed`
            throw new Error(errorMsg)
          }
        } else if (msg.type === 'error') {
          throw new Error(msg.message || 'Deployment failed')
        }
      })
      
      log('✅ Deployment complete!', 'success')
      toasts.success('Deployment successful!')
      
      // Refresh servers list in case new servers were provisioned
      await loadServersForDeploy()
      
    } catch (err) {
      // Handle error object properly
      let errorMsg = 'Unknown error'
      if (typeof err === 'string') {
        errorMsg = err
      } else if (err?.message) {
        errorMsg = err.message
      } else if (err?.detail) {
        errorMsg = err.detail
      } else if (err?.error) {
        errorMsg = err.error
      } else {
        try {
          errorMsg = JSON.stringify(err)
        } catch {
          errorMsg = String(err)
        }
      }
      log(`❌ Error: ${errorMsg}`, 'error')
      toasts.error(errorMsg)
    } finally {
      deploying = false
    }
  }
</script>

<div class="deploy-page">
  <div class="deploy-grid">
    <!-- Deploy Form -->
    <Card title="🚀 Deploy Application">
      <form on:submit={startDeployment}>
        <!-- App Info -->
        <div class="form-row three-col">
          <div class="form-group">
            <label for="deploy-name">App Name *</label>
            <input 
              id="deploy-name"
              type="text" 
              bind:value={name}
              placeholder="my-app"
              required
              pattern="[-a-z0-9]+"
              title="Lowercase letters, numbers, hyphens only"
            >
          </div>
          <div class="form-group">
            <label for="deploy-project">Project</label>
            <input 
              id="deploy-project"
              type="text" 
              bind:value={project}
              placeholder="my-project"
              pattern="[-a-z0-9]*"
            >
          </div>
          <div class="form-group">
            <label for="deploy-env">Environment</label>
            <select id="deploy-env" bind:value={environment}>
              {#each environments as env}
                <option value={env}>{env}</option>
              {/each}
            </select>
          </div>
        </div>
        
        <!-- Deploy Config Management -->
        <div class="config-bar">
          <span class="config-label">Config:</span>
          <Button variant="ghost" size="sm" on:click={loadDeployConfig} title="Load saved config">
            📥 Load
          </Button>
          <Button variant="ghost" size="sm" on:click={saveDeployConfig} title="Save current settings">
            💾 Save
          </Button>
          <Button variant="ghost" size="sm" on:click={toggleExcludePatterns} title="Edit exclusion patterns">
            🚫 Exclusions
          </Button>
          {#if configStatus}
            <span class="config-status">{configStatus}</span>
          {/if}
        </div>
        
        <!-- Exclusion Patterns Editor -->
        {#if showExcludePatterns}
          <div class="exclude-editor">
            <div class="exclude-header">
              <label>Exclusion Patterns</label>
              <Button variant="ghost" size="sm" on:click={resetExcludePatterns}>Reset to Defaults</Button>
            </div>
            <textarea 
              bind:value={excludePatternsText}
              rows="6"
              placeholder="node_modules/&#10;__pycache__/&#10;*.pyc&#10;.git/"
            ></textarea>
            <small>One pattern per line. Applied to folder uploads and git clones.</small>
          </div>
        {/if}
        
        <div class="form-group">
          <label for="deploy-tags">Tags <small>(comma-separated)</small></label>
          <input 
            id="deploy-tags"
            type="text" 
            bind:value={tags}
            placeholder="api, backend, v2"
          >
        </div>
        
        <!-- Source Type -->
        <div class="form-group">
          <label>Source Type *</label>
          <div class="source-radio-group">
            <label class="source-option" class:active={sourceType === 'code'}>
              <input type="radio" bind:group={sourceType} value="code">
              📁 Local Code
            </label>
            <label class="source-option" class:active={sourceType === 'git'}>
              <input type="radio" bind:group={sourceType} value="git">
              📦 Git Repo
            </label>
            <label class="source-option" class:active={sourceType === 'image'}>
              <input type="radio" bind:group={sourceType} value="image">
              🐳 Registry
            </label>
            <label class="source-option" class:active={sourceType === 'image_file'}>
              <input type="radio" bind:group={sourceType} value="image_file">
              📦 Local Image
            </label>
          </div>
        </div>
        
        <!-- Local Code Source (Build Folders) -->
        {#if sourceType === 'code'}
          <div class="source-config">
            <div class="form-group">
              <label>Build Folders</label>
              
              <!-- Drop zone for drag & drop -->
              <div 
                class="folder-drop-zone"
                class:dragover={isDraggingFolder}
                on:dragenter={handleDragEnter}
                on:dragleave={handleDragLeave}
                on:dragover={handleDragOver}
                on:drop={handleDrop}
              >
                {#if isDraggingFolder}
                  <div class="drop-overlay">
                    <span class="drop-icon">📂</span>
                    <span>Drop folder here</span>
                  </div>
                {/if}
              
                <!-- Hidden folder picker -->
                <input 
                  type="file" 
                  bind:this={folderPickerRef}
                  webkitdirectory
                  directory
                  multiple
                  style="display: none;"
                  on:change={onFolderPicked}
                >
                
                <!-- Folders list -->
                {#if buildFolders.length > 0}
                  <div class="folder-list">
                    {#each buildFolders as folder, i}
                      <div class="folder-item">
                        <span class="folder-icon">{folder.isMain ? '📁' : '📂'}</span>
                        <strong>{folder.name}/</strong>
                        <Badge variant={folder.isMain ? 'success' : 'secondary'}>
                          {folder.isMain ? 'MAIN' : 'dependency'}
                        </Badge>
                        <span class="file-count">{folder.fileCount} files</span>
                        {#if !folder.isMain}
                          <button type="button" class="set-main-btn" on:click={() => setFolderAsMain(i)} title="Set as main">⭐</button>
                        {/if}
                        <button type="button" class="remove-btn" on:click={() => removeBuildFolder(i)}>✕</button>
                      </div>
                    {/each}
                  </div>
                {/if}
                
                <!-- Add folder button -->
                <div class="folder-actions">
                  <Button size="sm" on:click={addBuildFolderUI}>
                    ➕ Add Folder
                  </Button>
                  <span class="drop-hint">or drag & drop folders here</span>
                </div>
              </div>
              
              <!-- Status info -->
              <div class="code-selection-info" class:success={buildFolders.some(f => f.isMain)} class:warning={buildFolders.length > 0 && !buildFolders.some(f => f.isMain)}>
                {#if buildFolders.length === 0}
                  No folders selected. Add your main service folder and any dependencies.
                {:else if !buildFolders.some(f => f.isMain)}
                  ⚠️ No main folder selected. Click ⭐ to set one as main.
                {:else}
                  {@const mainFolder = buildFolders.find(f => f.isMain)}
                  {@const depCount = buildFolders.filter(f => !f.isMain).length}
                  ✓ Main: <strong>{mainFolder.name}/</strong>
                  {#if depCount > 0}
                    + {depCount} dependenc{depCount === 1 ? 'y' : 'ies'}
                  {/if}
                {/if}
              </div>
              
              <!-- Remember folders checkbox -->
              <label class="checkbox-label small-check">
                <input type="checkbox" bind:checked={rememberFolders}>
                <span>Remember folder configuration for this service</span>
              </label>
            </div>
            
            <!-- Dockerfile Preview -->
            {#if showDockerfilePreview}
              <div class="dockerfile-preview">
                <div class="dockerfile-header">
                  <label>
                    🐳 Dockerfile
                    <Badge variant={dockerfileSource === 'from folder' ? 'success' : dockerfileSource === 'multi-folder' ? 'info' : 'warning'}>
                      {dockerfileSource}
                    </Badge>
                  </label>
                </div>
                <textarea 
                  bind:value={dockerfile}
                  rows="8"
                  class="dockerfile-editor"
                  spellcheck="false"
                ></textarea>
                <div class="dockerfile-quick-fields">
                  <select bind:value={dockerfileQuickFrom} on:change={() => updateDockerfileField('from')}>
                    <option value="">FROM...</option>
                    <option value="python:3.11-slim">python:3.11-slim</option>
                    <option value="python:3.12-slim">python:3.12-slim</option>
                    <option value="node:20-alpine">node:20-alpine</option>
                    <option value="node:18-alpine">node:18-alpine</option>
                    <option value="golang:1.21-alpine">golang:1.21-alpine</option>
                    <option value="nginx:alpine">nginx:alpine</option>
                  </select>
                  <input 
                    type="text"
                    bind:value={dockerfileQuickCmd}
                    on:change={() => updateDockerfileField('cmd')}
                    placeholder="CMD (e.g. uvicorn main:app ...)"
                  >
                </div>
              </div>
            {/if}
          </div>
        {/if}
        
        <!-- Git Source -->
        {#if sourceType === 'git'}
          <div class="source-config">
            <div class="form-group">
              <label for="git-url">Git Repository URL *</label>
              <input 
                id="git-url"
                type="url" 
                bind:value={gitUrl}
                placeholder="https://github.com/user/repo"
              >
              <small>HTTPS URL (SSH not supported)</small>
            </div>
            
            <div class="form-group">
              <label for="git-branch">Branch</label>
              <input 
                id="git-branch"
                type="text" 
                bind:value={gitBranch}
                placeholder="main"
              >
            </div>
            
            <div class="form-group">
              <label>Folders to Include</label>
              {#if gitFolders.length > 0}
                <div class="folder-list">
                  {#each gitFolders as folder, i}
                    <div class="folder-item">
                      <span>{folder.isMain ? '📁' : '📂'}</span>
                      <strong>{folder.path}</strong>
                      <Badge variant={folder.isMain ? 'success' : 'secondary'}>
                        {folder.isMain ? 'MAIN' : 'dependency'}
                      </Badge>
                      <button type="button" class="remove-btn" on:click={() => removeGitFolder(i)}>✕</button>
                    </div>
                  {/each}
                </div>
              {/if}
              <div class="folder-input">
                <input 
                  type="text" 
                  bind:value={gitFolderInput}
                  placeholder="e.g. services/my_api"
                >
                <Button size="sm" on:click={() => addGitFolder(true)}>+ Main</Button>
                <Button variant="ghost" size="sm" on:click={() => addGitFolder(false)}>+ Dep</Button>
              </div>
              <small>Leave empty to use entire repo. Add paths for multi-folder builds (main folder contains Dockerfile).</small>
            </div>
            
            <details class="private-repo">
              <summary>🔐 Private repository?</summary>
              <div class="form-group">
                <label for="git-token">Personal Access Token</label>
                <input 
                  id="git-token"
                  type="password" 
                  bind:value={gitToken}
                  placeholder="ghp_xxxxxxxxxxxx"
                >
                <small>Needs <code>repo</code> scope for private repos</small>
              </div>
            </details>
          </div>
        {/if}
        
        <!-- Registry Image Source -->
        {#if sourceType === 'image'}
          <div class="source-config">
            <div class="form-group">
              <label for="image-url">Docker Image *</label>
              <input 
                id="image-url"
                type="text" 
                bind:value={imageUrl}
                placeholder="registry.digitalocean.com/my-registry/app:latest"
              >
              <small>Full image URL from DO Registry or Docker Hub</small>
            </div>
          </div>
        {/if}
        
        <!-- Local Image File Source -->
        {#if sourceType === 'image_file'}
          <div class="source-config">
            <div class="form-group">
              <label for="image-file">Docker Image File (.tar) *</label>
              <input 
                id="image-file"
                type="file" 
                accept=".tar,.tar.gz"
                on:change={handleImageFileSelect}
              >
              {#if imageFile}
                <div class="file-selected">
                  📦 {imageFile.name} ({(imageFile.size / 1024 / 1024).toFixed(2)} MB)
                </div>
              {/if}
              <small>Export from Docker with: <code>docker save myimage:latest -o image.tar</code></small>
            </div>
            
            <div class="form-group">
              <label for="image-name">Image Name *</label>
              <input 
                id="image-name"
                type="text" 
                bind:value={imageName}
                placeholder="myapp:latest"
              >
              <small>The image name/tag as it appears in the tar file</small>
            </div>
            
            <div class="form-row">
              <div class="form-group">
                <label for="container-port">Container Port</label>
                <input 
                  id="container-port"
                  type="number" 
                  bind:value={containerPort}
                  placeholder={port}
                >
              </div>
              <div class="form-group">
                <label for="host-port">Host Port</label>
                <input 
                  id="host-port"
                  type="number" 
                  bind:value={hostPort}
                  placeholder={port}
                >
              </div>
            </div>
          </div>
        {/if}
        
        <!-- Port -->
        <div class="form-group">
          <label for="deploy-port">App Port</label>
          <input 
            id="deploy-port"
            type="number" 
            bind:value={port}
            min="1"
            max="65535"
          >
          <small>Port your app listens on inside the container</small>
        </div>
        
        <!-- Environment Variables (collapsible) -->
        <div class="collapsible-section" class:expanded={showEnvVars}>
          <button type="button" class="section-toggle" on:click={() => showEnvVars = !showEnvVars}>
            <span class="toggle-icon">{showEnvVars ? '▼' : '▶'}</span>
            <span>Environment Variables</span>
            {#if envVars.trim()}
              <Badge variant="info">{envVars.trim().split('\n').filter(l => l.trim()).length} vars</Badge>
            {/if}
          </button>
          {#if showEnvVars}
            <div class="section-content">
              <textarea 
                id="deploy-envvars"
                bind:value={envVars}
                rows="3"
                placeholder="KEY=value&#10;ANOTHER_KEY=value"
              ></textarea>
              <small>One per line: KEY=value</small>
            </div>
          {/if}
        </div>
        
        <!-- Service Configuration (collapsible) -->
        <div class="collapsible-section" class:expanded={showServiceConfig}>
          <button type="button" class="section-toggle" on:click={() => showServiceConfig = !showServiceConfig}>
            <span class="toggle-icon">{showServiceConfig ? '▼' : '▶'}</span>
            <span>🔧 Service Configuration</span>
            {#if setupDomain || Object.values(dependencies).some(d => d)}
              <Badge variant="info">configured</Badge>
            {/if}
          </button>
          {#if showServiceConfig}
            <div class="section-content service-config">
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={autoEnv}>
                <span>Auto-inject service discovery</span>
              </label>
              <small>Injects DATABASE_URL, REDIS_URL, etc. based on dependencies</small>
              
              {#if autoEnv}
                <div class="dependencies">
                  <label>Dependencies:</label>
                  <div class="dep-list">
                    <label class="dep-item">
                      <input type="checkbox" bind:checked={dependencies.postgres}>
                      🐘 PostgreSQL
                    </label>
                    <label class="dep-item">
                      <input type="checkbox" bind:checked={dependencies.redis}>
                      ⚡ Redis
                    </label>
                    <label class="dep-item">
                      <input type="checkbox" bind:checked={dependencies.mysql}>
                      🐬 MySQL
                    </label>
                    <label class="dep-item">
                      <input type="checkbox" bind:checked={dependencies.mongo}>
                      🍃 MongoDB
                    </label>
                  </div>
                </div>
              {/if}
              
              <div class="config-divider"></div>
              
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={persistData}>
                <span>💾 Persist data (mount volume)</span>
              </label>
              <small>Mounts /data volume for databases and stateful services</small>
              
              <div class="config-divider"></div>
              
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={setupDomain}>
                <span>🌐 Setup domain (Cloudflare)</span>
              </label>
              <small>Auto-provision subdomain with SSL via Cloudflare</small>
              
              {#if setupDomain}
                <div class="domain-config">
                  <div class="domain-preview">
                    <label>Domain Preview:</label>
                    <code>{domainPreview || 'app-project-env.domain.com'}</code>
                  </div>
                  
                  <div class="form-group">
                    <label for="base-domain">Base Domain</label>
                    <input 
                      id="base-domain"
                      type="text" 
                      bind:value={baseDomain}
                      placeholder="example.com"
                    >
                  </div>
                  
                  <div class="form-group">
                    <label for="domain-aliases">Custom Aliases <small>(optional)</small></label>
                    <input 
                      id="domain-aliases"
                      type="text" 
                      bind:value={domainAliases}
                      placeholder="api.myclient.com, app.example.com"
                    >
                    <small>Comma-separated custom domains (requires DNS setup)</small>
                  </div>
                </div>
              {/if}
            </div>
          {/if}
        </div>
        
        <!-- Server Selection -->
        <div class="server-selection">
          <div class="server-header">
            <div class="server-title">
              <span>🖥️ Servers</span>
              <Badge variant="info">{selectedServers.size} selected</Badge>
            </div>
            <div class="server-actions">
              <Button variant="ghost" size="sm" on:click={() => selectAllServers(true)}>✓ All</Button>
              <Button variant="ghost" size="sm" on:click={() => selectAllServers(false)}>✕ None</Button>
            </div>
          </div>
          
          <div class="server-list">
            {#if !filteredServers || filteredServers.length === 0}
              <div class="empty">No servers in {selectedRegion || 'any region'}</div>
            {:else}
              {#each filteredServers as server}
                {@const ip = server.ip || server.networks?.v4?.[0]?.ip_address}
                {#if ip}
                  <label class="server-item" class:selected={selectedServers.has(ip)}>
                    <input 
                      type="checkbox" 
                      checked={selectedServers.has(ip)}
                      on:change={() => toggleServer(ip)}
                    >
                    <span class="server-name">{server.name || 'unnamed'}</span>
                    <code class="server-ip">{ip}</code>
                    {#if server.project}
                      <Badge variant="info">{server.project}</Badge>
                    {/if}
                  </label>
                {/if}
              {/each}
            {/if}
          </div>
          
          <!-- Provisioning options (collapsible) -->
          <div class="collapsible-section" class:expanded={showProvisioning}>
            <button type="button" class="section-toggle" on:click={() => showProvisioning = !showProvisioning}>
              <span class="toggle-icon">{showProvisioning ? '▼' : '▶'}</span>
              <span>➕ New Server Provisioning</span>
              {#if additionalServers > 0}
                <Badge variant="warning">{additionalServers} new</Badge>
              {/if}
            </button>
            {#if showProvisioning}
              <div class="section-content provisioning-config">
                <div class="form-row three-col">
                  <div class="form-group">
                    <label for="snapshot-select">Snapshot {#if additionalServers > 0}*{/if}</label>
                    <select id="snapshot-select" bind:value={selectedSnapshot}>
                      <option value="">Select snapshot...</option>
                      {#each $snapshots || [] as snap}
                        <option value={snap.id}>{snap.name}</option>
                      {/each}
                    </select>
                  </div>
                  <div class="form-group">
                    <label for="region-select">Region</label>
                    <select id="region-select" bind:value={selectedRegion}>
                      {#each regions || [] as region}
                        <option value={region.slug}>{region.name || region.slug}</option>
                      {/each}
                    </select>
                  </div>
                  <div class="form-group">
                    <label for="size-select">Size</label>
                    <select id="size-select" bind:value={selectedSize}>
                      {#each sizes || [] as size}
                        <option value={size.slug}>{size.description || size.slug}</option>
                      {/each}
                    </select>
                  </div>
                </div>
                
                <div class="new-servers">
                  <span>New servers to provision:</span>
                  <div class="number-spinner">
                    <button type="button" on:click={() => additionalServers = Math.max(0, additionalServers - 1)}>−</button>
                    <input type="number" bind:value={additionalServers} min="0" max="10">
                    <button type="button" on:click={() => additionalServers = Math.min(10, additionalServers + 1)}>+</button>
                  </div>
                  {#if additionalServers > 0 && !selectedSnapshot}
                    <small class="warning">⚠️ Select a snapshot for new servers</small>
                  {/if}
                </div>
              </div>
            {/if}
          </div>
        </div>
        
        <Button variant="primary" type="submit" disabled={deploying}>
          {#if deploying}
            Deploying...
          {:else}
            🚀 Deploy
          {/if}
        </Button>
      </form>
    </Card>
    
    <!-- Progress Panel -->
    <Card title="📋 Deployment Progress">
      {#if deploying || logs.length > 0}
        <div class="progress-section">
          <div class="progress-bar">
            <div class="progress-fill" style="width: {progress}%"></div>
          </div>
          <div class="log-output">
            {#each logs as log}
              <div class="log-line {log.type}">
                <span class="log-time">{log.time.toLocaleTimeString()}</span>
                {@html linkifyUrls(log.message)}
              </div>
            {/each}
          </div>
          
          <!-- Success result box -->
          {#if deployResult && deployResult.success}
            <div class="deploy-success-box">
              <div class="result-header">
                <h4>✅ Deployment Complete</h4>
                <span class="env-badge">{environment.toUpperCase()}</span>
              </div>
              
              {#if deployResult.domain}
                <div class="result-section">
                  <span class="result-label">Domain:</span>
                  <a href="https://{deployResult.domain}" target="_blank" class="result-link">
                    https://{deployResult.domain}
                  </a>
                </div>
              {/if}
              
              {#if deployResult.servers && deployResult.servers.length > 0}
                <div class="result-section">
                  <span class="result-label">Servers:</span>
                  <div class="server-links">
                    {#each deployResult.servers.filter(s => s.success) as server}
                      <div class="server-link-row">
                        <a href="{server.url}" target="_blank" class="result-link">{server.url}</a>
                        <button class="log-btn" on:click={() => window.open(`/api/v1/infra/logs/${server.ip}/${server.container_name || deployResult.container_name || name}`, '_blank')}>
                          📋 Logs
                        </button>
                      </div>
                    {/each}
                  </div>
                </div>
                
                <!-- Failed servers section -->
                {#if deployResult.servers.some(s => !s.success)}
                  <div class="failed-servers-section">
                    <span class="result-label" style="color: #fef3c7;">Failed Servers:</span>
                    {#each deployResult.servers.filter(s => !s.success) as server}
                      <div class="server-link-row">
                        <span style="color: #fef3c7;">❌ {server.ip}: {server.error || 'Unknown error'}</span>
                        <button class="log-btn" on:click={() => window.open(`/api/v1/infra/logs/${server.ip}/${server.container_name || deployResult.container_name || name}`, '_blank')}>
                          📋 Logs
                        </button>
                      </div>
                    {/each}
                  </div>
                {/if}
              {/if}
            </div>
          {:else if deployResult && !deployResult.success}
            <!-- Failure result box -->
            <div class="deploy-failure-box">
              <div class="result-header">
                <h4>❌ Deployment Failed</h4>
                <span class="env-badge">{environment.toUpperCase()}</span>
              </div>
              {#if deployResult.error}
                <p>{deployResult.error}</p>
              {/if}
              
              {#if deployResult.servers && deployResult.servers.length > 0}
                <div class="result-section" style="margin-top: 12px;">
                  <span class="result-label">Server Status:</span>
                  <div class="server-links">
                    {#each deployResult.servers as server}
                      <div class="server-link-row">
                        <span>
                          {#if server.success}
                            ✅ {server.ip}
                          {:else}
                            ❌ {server.ip}{#if server.error}: {server.error}{/if}
                          {/if}
                        </span>
                        <button class="log-btn" on:click={() => window.open(`/api/v1/infra/logs/${server.ip}/${server.container_name || deployResult.container_name || name}`, '_blank')}>
                          📋 Logs
                        </button>
                      </div>
                    {/each}
                  </div>
                </div>
              {:else}
                <p style="margin-top: 8px; opacity: 0.8;">No server details available</p>
              {/if}
            </div>
          {/if}
        </div>
      {:else}
        <div class="empty-state">
          <p>No deployment in progress</p>
          <p class="hint">Fill in the form and click Deploy to start</p>
        </div>
      {/if}
    </Card>
  </div>
</div>

<!-- Cleanup Confirmation Modal -->
<Modal 
  bind:open={showCleanupConfirm}
  title="⚠️ Service Already Running"
  width="500px"
  on:close={() => { showCleanupConfirm = false; pendingDeployAction = null }}
>
  <div class="cleanup-confirm-content">
    <p>
      This service is currently running on <strong>{cleanupServers.length + [...selectedServers].length}</strong> servers.
      You're deploying to <strong>{[...selectedServers].length}</strong> servers.
    </p>
    
    <p>Stop containers on the following servers?</p>
    
    <div class="cleanup-server-list">
      {#each cleanupServers as server}
        <div class="cleanup-server-item">
          <span class="server-name">{server.name || server.ip}</span>
          <span class="server-ip">{server.ip}</span>
        </div>
      {/each}
    </div>
  </div>
  
  <div slot="footer">
    <Button variant="primary" on:click={confirmCleanupAndDeploy}>
      Proceed
    </Button>
    <Button variant="ghost" on:click={() => { showCleanupConfirm = false; pendingDeployAction = null }}>
      Cancel
    </Button>
  </div>
</Modal>

<style>
  .deploy-page {
    padding: 0;
  }
  
  .deploy-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  
  /* Collapsible Sections */
  .collapsible-section {
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 16px;
    overflow: hidden;
    background: var(--bg-secondary);
  }
  
  .collapsible-section.expanded {
    background: var(--bg-tertiary);
  }
  
  .section-toggle {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    background: transparent;
    border: none;
    color: var(--text);
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    text-align: left;
    transition: background 0.15s ease;
  }
  
  .section-toggle:hover {
    background: var(--bg-hover);
  }
  
  .toggle-icon {
    font-size: 0.75rem;
    color: var(--text-muted);
    width: 12px;
  }
  
  .section-content {
    padding: 16px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
  }
  
  .section-content textarea {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    font-size: 0.875rem;
    resize: vertical;
  }
  
  .section-content small {
    display: block;
    margin-top: 6px;
    font-size: 0.75rem;
    color: var(--text-muted2);
  }
  
  .form-row {
    display: grid;
    gap: 12px;
    margin-bottom: 16px;
  }
  
  .form-row.three-col {
    grid-template-columns: 1fr 1fr 1fr;
  }
  
  .provisioning-config {
    padding: 0;
  }
  
  .provisioning-config .form-row {
    margin-bottom: 12px;
  }

  .provisioning-config select {
    min-width: 0;
    width: 100%;
  }
  
  .provisioning-config .new-servers {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
    margin-top: 8px;
  }
  
  .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 16px;
  }
  
  .form-group label {
    font-size: 0.875rem;
    color: var(--text-muted);
  }
  
  .form-group small {
    font-size: 0.75rem;
    color: var(--text-muted2);
  }
  
  .form-group input,
  .form-group select,
  .form-group textarea {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .form-group input:focus,
  .form-group select:focus,
  .form-group textarea:focus {
    outline: none;
    border-color: var(--primary);
    background: var(--input-focus-bg);
  }
  
  .source-radio-group {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  
  .source-option {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: var(--bg-input);
    border: 2px solid var(--border);
    border-radius: 20px;
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
  }
  
  .source-option:hover {
    border-color: var(--primary);
  }
  
  .source-option.active {
    background: linear-gradient(135deg, var(--primary), var(--primary2));
    border-color: var(--primary);
    color: white;
  }
  
  .source-option input {
    display: none;
  }
  
  .source-config {
    padding: 16px;
    background: var(--bg-input);
    border-radius: 12px;
    margin-bottom: 16px;
  }
  
  .service-config {
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;
  }
  
  .config-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
    font-weight: 600;
  }
  
  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }
  
  .checkbox-label input {
    width: auto;
  }
  
  .dependencies {
    margin-top: 12px;
    padding: 12px;
    background: var(--bg-card);
    border-radius: 8px;
  }
  
  .dep-list {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 8px;
  }
  
  .dep-item {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }
  
  .dep-item input {
    width: auto;
  }
  
  .config-divider {
    height: 1px;
    background: var(--border);
    margin: 16px 0;
  }
  
  .domain-config {
    margin-top: 12px;
    padding: 12px;
    background: var(--bg-card);
    border-radius: 8px;
  }
  
  .domain-preview {
    margin-bottom: 12px;
  }
  
  .domain-preview label {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  
  .domain-preview code {
    display: block;
    margin-top: 4px;
    padding: 8px 12px;
    background: var(--bg-input);
    border-radius: 4px;
    color: var(--primary);
    font-family: monospace;
  }
  
  .server-selection {
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 16px;
  }
  
  .server-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 12px;
    background: var(--bg-input);
  }
  
  .server-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 500;
  }
  
  .server-actions {
    display: flex;
    gap: 4px;
  }
  
  .server-list {
    max-height: 200px;
    overflow-y: auto;
  }
  
  .server-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.15s;
  }
  
  .server-item:hover {
    background: var(--table-row-hover);
  }
  
  .server-item.selected {
    background: rgba(109,92,255,.1);
  }
  
  .server-item input {
    width: auto;
  }
  
  .server-name {
    flex: 1;
    font-weight: 500;
  }
  
  .server-ip {
    font-size: 0.75rem;
    padding: 2px 6px;
    background: var(--bg-input);
    border-radius: 4px;
  }
  
  .new-servers {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: var(--bg-input);
    font-size: 0.85rem;
  }
  
  .number-spinner {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }
  
  .number-spinner button {
    width: 32px;
    height: 32px;
    border: none;
    background: var(--btn-ghost-bg);
    cursor: pointer;
    font-size: 1rem;
    color: var(--text);
  }
  
  .number-spinner button:hover {
    background: var(--btn-bg-hover);
  }
  
  .number-spinner input {
    width: 40px;
    height: 32px;
    border: none;
    border-left: 1px solid var(--border);
    border-right: 1px solid var(--border);
    text-align: center;
    background: transparent;
    border-radius: 0;
  }
  
  .progress-section {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .progress-bar {
    height: 6px;
    background: var(--bg-input);
    border-radius: 3px;
    overflow: hidden;
  }
  
  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), var(--primary2));
    transition: width 0.3s ease;
  }
  
  .log-output {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    max-height: 300px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 0.8rem;
  }
  
  .log-line {
    margin-bottom: 4px;
    line-height: 1.4;
    color: var(--text);
  }
  
  .log-line.success { color: var(--success); }
  .log-line.error { color: var(--danger); }
  .log-line.warning { color: var(--warning); }
  
  .log-time {
    color: var(--text-muted);
    margin-right: 8px;
  }
  
  .log-link {
    color: var(--primary);
    text-decoration: underline;
  }
  
  .log-link:hover {
    color: var(--primary-hover);
  }
  
  /* Deploy result box */
  .deploy-success-box {
    margin-top: 16px;
    padding: 16px;
    background: #10b981;
    color: white;
    border-radius: 8px;
  }
  
  .deploy-failure-box {
    margin-top: 16px;
    padding: 16px;
    background: #ef4444;
    color: white;
    border-radius: 8px;
  }
  
  .result-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }
  
  .deploy-success-box h4,
  .deploy-failure-box h4 {
    margin: 0;
    color: white;
    font-size: 1rem;
  }
  
  .env-badge {
    background: rgba(255, 255, 255, 0.2);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
  }
  
  .result-section {
    margin-bottom: 12px;
  }
  
  .result-section:last-child {
    margin-bottom: 0;
  }
  
  .failed-servers-section {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(255, 255, 255, 0.3);
  }
  
  .result-label {
    display: block;
    font-size: 0.75rem;
    color: rgba(255, 255, 255, 0.8);
    margin-bottom: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .result-link {
    color: white;
    text-decoration: underline;
    font-family: monospace;
  }
  
  .result-link:hover {
    color: rgba(255, 255, 255, 0.9);
  }
  
  .server-links {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .server-link-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  
  .log-btn {
    padding: 4px 8px;
    font-size: 0.75rem;
    background: rgba(255, 255, 255, 0.2);
    border: none;
    border-radius: 6px;
    color: white;
    cursor: pointer;
    transition: all 0.15s;
  }
  
  .log-btn:hover {
    background: rgba(255, 255, 255, 0.3);
  }
  
  .empty-state {
    text-align: center;
    padding: 40px;
    color: var(--text-muted);
  }
  
  .empty-state .hint {
    font-size: 0.8rem;
    color: var(--text-muted2);
    margin-top: 8px;
  }
  
  .empty {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
  }
  
  .new-server-config {
    padding: 12px;
    background: var(--bg-input);
    border-top: 1px solid var(--border);
  }
  
  /* File Upload Zone */
  .file-upload-zone {
    position: relative;
    border: 2px dashed var(--border);
    border-radius: 12px;
    padding: 24px;
    text-align: center;
    transition: all 0.2s;
    cursor: pointer;
  }
  
  .file-upload-zone:hover,
  .file-upload-zone.dragover {
    border-color: var(--primary);
    background: rgba(99, 102, 241, 0.05);
  }
  
  .file-upload-zone input[type="file"] {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
  }
  
  .upload-prompt {
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: var(--text-muted);
  }
  
  .upload-prompt small {
    font-size: 0.75rem;
    color: var(--text-muted2);
  }
  
  .file-info {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }
  
  .file-size {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .remove-file {
    background: var(--danger);
    color: white;
    border: none;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    cursor: pointer;
    font-size: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .new-server-config .form-row {
    margin-bottom: 0;
  }
  
  .new-server-config .form-group {
    margin-bottom: 8px;
  }
  
  .warning {
    display: block;
    color: var(--warning);
    font-size: 0.75rem;
  }
  
  .config-bar {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 8px;
    align-items: center;
  }
  
  .config-label {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  
  .config-status {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-left: auto;
  }
  
  .exclude-editor {
    margin-bottom: 16px;
    padding: 12px;
    background: var(--bg-secondary);
    border-radius: 8px;
  }
  
  .exclude-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  
  .exclude-header label {
    font-weight: 500;
  }
  
  .exclude-editor textarea {
    width: 100%;
    font-family: monospace;
    font-size: 0.85rem;
    padding: 8px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    resize: vertical;
  }
  
  .exclude-editor small {
    display: block;
    margin-top: 4px;
    color: var(--text-muted);
    font-size: 0.75rem;
  }
  
  /* Build folder styles */
  .folder-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 8px;
  }
  
  .folder-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--bg-input);
    border-radius: 8px;
    font-size: 0.85rem;
  }
  
  .folder-item .folder-icon {
    font-size: 1rem;
  }
  
  .folder-item strong {
    flex: 1;
  }
  
  .folder-item .file-count {
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  
  .folder-item .set-main-btn {
    background: none;
    border: none;
    cursor: pointer;
    opacity: 0.5;
    padding: 2px;
  }
  
  .folder-item .set-main-btn:hover {
    opacity: 1;
  }
  
  .remove-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 1rem;
    padding: 2px 6px;
    border-radius: 4px;
  }
  
  .remove-btn:hover {
    background: var(--danger);
    color: white;
  }
  
  .folder-actions {
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  
  .drop-hint {
    font-size: 0.8rem;
    color: var(--text-muted);
  }
  
  .folder-drop-zone {
    position: relative;
    border: 2px dashed var(--border);
    border-radius: 12px;
    padding: 16px;
    transition: all 0.2s;
    min-height: 80px;
  }
  
  .folder-drop-zone.dragover {
    border-color: var(--primary);
    background: rgba(99, 102, 241, 0.05);
  }
  
  .drop-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    background: rgba(99, 102, 241, 0.1);
    border-radius: 10px;
    z-index: 10;
    color: var(--primary);
    font-weight: 500;
  }
  
  .drop-overlay .drop-icon {
    font-size: 2rem;
  }
  
  .code-selection-info {
    padding: 8px 12px;
    background: var(--bg-input);
    border-radius: 8px;
    font-size: 0.85rem;
    color: var(--text-muted);
    margin-bottom: 8px;
  }
  
  .code-selection-info.success {
    color: var(--success);
  }
  
  .code-selection-info.warning {
    color: var(--warning);
  }
  
  .small-check {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  
  /* Dockerfile preview */
  .dockerfile-preview {
    margin-top: 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }
  
  .dockerfile-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
  }
  
  .dockerfile-header label {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-weight: 500;
  }
  
  .dockerfile-editor {
    width: 100%;
    font-family: monospace;
    font-size: 0.8rem;
    padding: 12px;
    background: var(--bg-input);
    border: none;
    color: var(--text);
    resize: vertical;
  }
  
  .dockerfile-quick-fields {
    display: flex;
    gap: 8px;
    padding: 8px 12px;
    background: var(--panel-bg);
    border-top: 1px solid var(--border);
  }
  
  .dockerfile-quick-fields select,
  .dockerfile-quick-fields input {
    padding: 10px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    font-size: 0.875rem;
  }
  
  .dockerfile-quick-fields select {
    flex: 1;
    min-width: 150px;
  }
  
  .dockerfile-quick-fields input {
    flex: 3;
  }
  
  .dockerfile-quick-fields select:focus,
  .dockerfile-quick-fields input:focus {
    outline: none;
    border-color: var(--primary);
    background: var(--input-focus-bg);
  }
  
  /* Image file source */
  .file-selected {
    margin-top: 8px;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 8px;
    font-size: 0.85rem;
  }
  
  .form-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  
  /* Git folder input */
  .folder-input {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
  
  .folder-input input {
    flex: 1;
  }
  
  .private-repo {
    margin-top: 12px;
    padding: 12px;
    background: var(--bg-card);
    border-radius: 8px;
  }
  
  .private-repo summary {
    cursor: pointer;
    color: var(--text-muted);
    font-size: 0.85rem;
  }

  @media (max-width: 900px) {
    .deploy-grid {
      grid-template-columns: 1fr;
    }
    
    .form-row.three-col {
      grid-template-columns: 1fr;
    }
  }
  
  @media (max-width: 768px) {
    .form-row {
      grid-template-columns: 1fr !important;
      gap: 12px;
    }
    
    .form-row.three-col {
      grid-template-columns: 1fr !important;
    }
    
    .source-types {
      flex-wrap: wrap;
      gap: 8px;
    }
    
    .source-types label {
      flex: 1 1 calc(50% - 8px);
      min-width: 120px;
      font-size: 0.8rem;
      padding: 8px 12px;
    }
    
    .config-bar {
      flex-wrap: wrap;
      gap: 6px;
    }
    
    .config-label {
      width: 100%;
    }
    
    .config-status {
      margin-left: 0;
      width: 100%;
    }
    
    .server-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 8px;
    }
    
    .server-actions {
      width: 100%;
      display: flex;
      gap: 8px;
    }
    
    .provisioning-config {
      padding: 8px;
    }
    
    .provisioning-config .form-row {
      gap: 8px;
    }
    
    .new-servers {
      flex-wrap: wrap;
    }
    
    .dockerfile-quick-fields {
      flex-direction: column;
      gap: 8px;
    }
    
    .dockerfile-quick-fields select,
    .dockerfile-quick-fields input {
      width: 100%;
      min-width: 0;
    }
    
    .folder-input {
      flex-direction: column;
    }
    
    .folder-input input {
      width: 100%;
    }
    
    .domain-config .form-group {
      margin-bottom: 12px;
    }
    
    .exclude-header {
      flex-direction: column;
      align-items: flex-start;
      gap: 8px;
    }
  }
  
  @media (max-width: 480px) {
    .source-types label {
      flex: 1 1 100%;
    }
    
    .number-spinner {
      flex-wrap: nowrap;
    }
    
    .number-spinner input {
      width: 50px;
    }
    
    .folder-item {
      flex-wrap: wrap;
    }
    
    .server-item {
      flex-wrap: wrap;
      gap: 4px;
    }
    
    .server-ip {
      width: 100%;
      margin-left: 24px;
    }
  }
  
  /* Cleanup Confirmation Modal */
  .cleanup-confirm-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .cleanup-confirm-content p {
    margin: 0;
    line-height: 1.5;
  }
  
  .cleanup-server-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: var(--bg-input);
    border-radius: 8px;
    padding: 12px;
    max-height: 200px;
    overflow-y: auto;
  }
  
  .cleanup-server-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
  }
  
  .cleanup-server-item .server-name {
    font-weight: 500;
  }
  
  .cleanup-server-item .server-ip {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
</style>

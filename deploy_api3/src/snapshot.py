"""
Snapshot provisioning with template caching.
Uses typed entities.
"""

import os
import hmac
import hashlib
import asyncio
import aiohttp
from typing import Dict, Any, List, AsyncIterator, Optional
import asyncssh

from shared_libs.backend.cloud import AsyncDOClient

from .stores import snapshots, droplets
from .sse_streaming import StreamContext, sse_complete, sse_log
from . import agent_client


# =============================================================================
# Configuration
# =============================================================================

BASE_IMAGES = {
    'redis:7-alpine': 6379,
    'postgres:16-alpine': 5432,
    'mongo:7': 27017,
    'opensearchproject/opensearch:2': 9200,
    'mysql:8': 3306,
}

AGENT_VERSION = '1.0.0'
TEMPLATE_SNAPSHOT_NAME = '_template'


# =============================================================================
# Base Snapshot Creation
# =============================================================================

async def create_base_snapshot(
    db, user_id: str, region: str, do_token: str,
    images: List[str] = None, size: str = 's-1vcpu-1gb',
    cleanup_on_failure: bool = True,
) -> AsyncIterator[str]:
    """
    Create base snapshot from template (creating template if needed).
    
    Template: Docker + nginx + SSL + git + images (no agent, no firewall)
    Base: Template + agent + firewall + user restrictions
    
    Args:
        cleanup_on_failure: If False, keeps droplet on failure for SSH debugging
    """
    stream = StreamContext()
    do_droplet_id = None
    droplet_ip = None
    images = images or list(BASE_IMAGES.keys())
    ssh_key_path = os.environ.get('SSH_PRIVATE_KEY_PATH', os.path.expanduser('~/.ssh/id_ed25519'))
    
    try:
        async with AsyncDOClient(api_token=do_token) as client:
            
            # =================================================================
            # 1. Get or create template
            # =================================================================
            existing = await client.list_snapshots()
            template = next(
                (s for s in existing if s.name == TEMPLATE_SNAPSHOT_NAME), 
                None
            )
            
            if template:
                template_id = template.id
            else:
                result = {}
                async for event in _create_template(
                    client, stream, user_id, region, size, images, do_token, result,
                    cleanup_on_failure=cleanup_on_failure
                ):
                    yield event
                template_id = result.get('template_id')
                if not template_id:
                    return  # _create_template already yielded error
            
            # =================================================================
            # 2. Create base from template
            # =================================================================
            
            # Ensure SSH key exists and is registered with DO
            stream('Setting up SSH key...')
            yield sse_log(stream._logs[-1])
            
            ssh_key_id, ssh_messages = await _ensure_ssh_key(client, ssh_key_path)
            for msg, level in ssh_messages:
                stream(f'  {msg}')
                yield sse_log(stream._logs[-1], level)
            
            if not ssh_key_id:
                raise Exception(f'SSH key setup failed. Ensure private key exists at {ssh_key_path}')
            
            stream('Creating temp droplet from template...')
            yield sse_log(stream._logs[-1])
            
            droplet_result = await client.create_droplet(
                name='temp-base', region=region, size=size,
                image=template_id,
                tags=[f'user:{user_id}', 'temp-snapshot'],
                ssh_keys=[str(ssh_key_id)],
                wait=False,
            )
            do_droplet_id = droplet_result.id
            
            # Wait for IP
            droplet_ip, ip_messages = await _wait_for_ip(client, do_droplet_id)
            for msg, level in ip_messages:
                stream(msg)
                yield sse_log(stream._logs[-1], level)
            
            if not droplet_ip:
                raise Exception('Timeout waiting for IP')
            
            stream(f'Droplet ready at {droplet_ip}')
            yield sse_log(stream._logs[-1])
            
            # Wait for SSH
            stream('Waiting for SSH...')
            yield sse_log(stream._logs[-1])
            await asyncio.sleep(20)
            
            # Install agent + firewall + user restrictions
            async with asyncssh.connect(droplet_ip, username='root', known_hosts=None, client_keys=[ssh_key_path]) as conn:
                # Create agent user
                stream('Creating agent user...')
                yield sse_log(stream._logs[-1])
                
                await conn.run('useradd -r -s /bin/false nodeagent', check=True)
                await conn.run('usermod -aG docker nodeagent', check=True)
                
                # Set permissions for agent directories
                await conn.run('chown nodeagent:nodeagent /opt/node_agent', check=True)
                await conn.run('chown nodeagent:nodeagent /data', check=True)
                await conn.run('chown nodeagent:nodeagent /etc/nginx/sites-enabled', check=True)
                await conn.run('mkdir -p /etc/cron.d && chown nodeagent:nodeagent /etc/cron.d', check=True)
                
                # Agent
                stream('Installing node agent...')
                yield sse_log(stream._logs[-1])
                
                agent_path = os.path.join(os.path.dirname(__file__), '..', 'node_agent', 'agent.py')
                with open(agent_path, encoding='utf-8') as f:
                    agent_code = f.read()
                
                await conn.run(f"cat > /opt/node_agent/agent.py << 'AGENT_EOF'\n{agent_code}\nAGENT_EOF", check=True)
                await conn.run('chown nodeagent:nodeagent /opt/node_agent/agent.py', check=True)
                
                # Systemd service
                stream('Creating systemd service...')
                yield sse_log(stream._logs[-1])
                
                api_key = hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()
                
                # Detect managed mode: if client's DO token matches server's DO token,
                # we're deploying to our own infrastructure -> bind agent to VPC IP only
                server_do_token = os.environ.get('DO_TOKEN', '')
                is_managed = do_token == server_do_token and server_do_token != ''
                managed_mode_str = 'true' if is_managed else 'false'
                
                if is_managed:
                    stream('  Managed PaaS mode detected (same DO account)')
                    yield sse_log(stream._logs[-1])
                    stream('  -> Agent will bind to VPC IP only (more secure)')
                    yield sse_log(stream._logs[-1])
                else:
                    stream('  Customer mode detected (different DO account)')
                    yield sse_log(stream._logs[-1])
                    stream('  -> Agent will bind to 0.0.0.0 (accessible externally)')
                    yield sse_log(stream._logs[-1])
                
                service_content = f'''[Unit]
Description=Node Agent
After=network.target docker.service

[Service]
Type=simple
User=nodeagent
Group=nodeagent
Environment="NODE_AGENT_API_KEY={api_key}"
Environment="MANAGED_MODE={managed_mode_str}"
ExecStart=/usr/bin/python3 /opt/node_agent/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target'''
                
                await conn.run(f"cat > /etc/systemd/system/node-agent.service << 'EOF'\n{service_content}\nEOF", check=True)
                await conn.run('systemctl daemon-reload && systemctl enable node-agent', check=True)
                
                # Start agent for health check
                await conn.run('systemctl start node-agent', check=True)
                
                # Firewall
                stream('Configuring firewall...')
                yield sse_log(stream._logs[-1])
                
                await conn.run('ufw --force reset', check=True)
                await conn.run('ufw default deny incoming', check=True)
                await conn.run('ufw default allow outgoing', check=True)
                await conn.run('ufw allow 443/tcp', check=True)
                
                if is_managed:
                    # Managed mode: agent bound to VPC IP, allow 9999 from VPC only
                    await conn.run('ufw allow from 10.0.0.0/8 to any port 9999', check=True)
                else:
                    # Customer mode: agent on public IP, allow 9999 from anywhere
                    await conn.run('ufw allow 9999/tcp', check=True)
                
                for admin_ip in os.environ.get('ADMIN_IPS', '').split(','):
                    if admin_ip.strip():
                        await conn.run(f'ufw allow from {admin_ip.strip()} to any port 22', check=True)
                
                await conn.run('ufw --force enable', check=True)
            
            # =================================================================
            # 3. Verify node agent is healthy
            # =================================================================
            stream('Verifying node agent...')
            yield sse_log(stream._logs[-1])
            
            agent_ok, agent_msg = await _check_agent_health(droplet_ip, api_key)
            if not agent_ok:
                stream(f'Agent health check failed: {agent_msg}')
                yield sse_log(stream._logs[-1], 'error')
                
                # Get diagnostics
                diag = await _get_agent_diagnostics(droplet_ip, ssh_key_path)
                if diag:
                    for line in diag.split('\n')[:10]:
                        if line.strip():
                            stream(f'  {line.strip()[:100]}')
                            yield sse_log(stream._logs[-1])
                
                if cleanup_on_failure:
                    await client.delete_droplet(do_droplet_id, force=True)
                    stream('Droplet deleted')
                    yield sse_log(stream._logs[-1])
                else:
                    stream(f'DROPLET KEPT FOR DEBUGGING: ssh root@{droplet_ip}')
                    yield sse_log(stream._logs[-1])
                
                yield sse_complete(False, '', f'Node agent failed: {agent_msg}')
                return
            
            stream(f'Agent healthy: {agent_msg}')
            yield sse_log(stream._logs[-1])
            
            # =================================================================
            # 4. Remove SSH keys from droplet (security)
            # =================================================================
            stream('Removing SSH keys from droplet...')
            yield sse_log(stream._logs[-1])
            
            try:
                async with asyncssh.connect(droplet_ip, username='root', known_hosts=None, client_keys=[ssh_key_path]) as conn:
                    await conn.run('rm -f /root/.ssh/authorized_keys', check=False)
                    stream('SSH keys cleared - snapshot will have no SSH access')
                    yield sse_log(stream._logs[-1])
            except Exception as e:
                stream(f'Warning: could not clear SSH keys: {e}')
                yield sse_log(stream._logs[-1])
            
            # =================================================================
            # 5. Create snapshot
            # =================================================================
            stream('Powering off droplet...')
            yield sse_log(stream._logs[-1])
            await client.power_off_droplet(do_droplet_id)
            
            # Wait for power off
            for _ in range(30):
                info = await client.get_droplet(do_droplet_id)
                if info and info.status == 'off':
                    break
                await asyncio.sleep(2)
            
            stream('Creating snapshot...')
            yield sse_log(stream._logs[-1])
            snapshot = await client.create_snapshot_from_droplet(do_droplet_id, name='base')
            
            # Get snapshot info
            snap_list = await client.list_snapshots()
            do_snapshot = next((s for s in snap_list if s.name == 'base'), None)
            do_snapshot_id = do_snapshot.id if do_snapshot else str(snapshot.id)
            size_gb = do_snapshot.size_gigabytes if do_snapshot else 0
            
            # Cleanup temp droplet
            stream('Cleaning up temp droplet...')
            yield sse_log(stream._logs[-1])
            await client.delete_droplet(do_droplet_id, force=True)
            do_droplet_id = None
            
            # Save to DB
            snap = await snapshots.create(db, {
                'workspace_id': user_id,
                'do_snapshot_id': str(do_snapshot_id),
                'name': 'base',
                'region': region,
                'size_gigabytes': size_gb,
                'agent_version': AGENT_VERSION,
                'is_base': True,
                'is_managed': is_managed,
            })
            
            stream('Base snapshot ready!')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, snap.id)
    
    except Exception as e:
        error_msg = str(e)
        stream(f'Error: {error_msg}')
        yield sse_log(stream._logs[-1], 'error')
        
        # Cleanup on error
        if do_droplet_id:
            if cleanup_on_failure:
                try:
                    async with AsyncDOClient(api_token=do_token) as client:
                        await client.delete_droplet(do_droplet_id, force=True)
                    stream('Droplet deleted')
                    yield sse_log(stream._logs[-1])
                except:
                    pass
            else:
                stream(f'DROPLET KEPT FOR DEBUGGING: ssh root@{droplet_ip}')
                yield sse_log(stream._logs[-1])
        
        yield sse_complete(False, '', error_msg)


# =============================================================================
# Custom Snapshot Creation
# =============================================================================

async def create_custom_snapshot(
    db, user_id: str, do_token: str,
    git_repos: List[Dict] = None,
    source_zips: Dict[str, bytes] = None,
    dockerfile_content: str = None,
    snapshot_name: str = None,
    region: str = 'lon1',
    size: str = 's-1vcpu-1gb',
    base_snapshot_id: str = None,
    test_env_variables: List[str] = None,
) -> AsyncIterator[str]:
    """Create a custom snapshot with image baked in."""
    stream = StreamContext()
    droplet_id = None
    image_name = 'base'
    
    try:
        if not git_repos and not source_zips:
            raise Exception('Need git_repos or source_zips')
        
        snapshot_name = snapshot_name or f'custom-{user_id[:6]}'
        
        if not base_snapshot_id:
            base = await snapshots.get_base(db, user_id)
            if not base:
                raise Exception("No base snapshot. Run create_base_snapshot first.")
            base_snapshot_id = base.id
        
        base_snap = await snapshots.get(db, base_snapshot_id)
        is_managed = getattr(base_snap, 'is_managed', False) if base_snap else False
        
        stream('Creating temp droplet...')
        yield sse_log(stream._logs[-1])
        
        from .droplet import create_droplet
        droplet = await create_droplet(db, user_id, base_snapshot_id, region, size, do_token)
        if isinstance(droplet, dict) and droplet.get('error'):
            raise Exception(f"Droplet creation failed: {droplet['error']}")
        
        droplet_id = droplet['id']
        droplet_ip = droplet['ip']
        agent_ip = droplet.get('private_ip', droplet_ip) if is_managed else droplet_ip
        
        stream(f'Droplet ready at {droplet_ip}')
        yield sse_log(stream._logs[-1])
        
        stream('Building image...')
        yield sse_log(stream._logs[-1])
        
        result = await agent_client.build_image(
            agent_ip, image_name, do_token,
            git_repos=git_repos,
            source_zips=source_zips,
            dockerfile_content=dockerfile_content
        )
        
        if result.get('status') == 'failed':
            raise Exception(f"Build failed: {result.get('error')}")
        
        stream(f'Image built: {image_name}')
        yield sse_log(stream._logs[-1])
        
        stream('Test run...')
        yield sse_log(stream._logs[-1])
        
        container_name = 'test-run'
        result = await agent_client.start_container(
            agent_ip, container_name, image_name,
            test_env_variables or [], 8000, 19999, do_token
        )
        if result.get('error'):
            raise Exception(f"Test start failed: {result['error']}")
        
        await asyncio.sleep(5)
        status = await agent_client.container_status(agent_ip, container_name, do_token)
        
        if not status.get('running'):
            health = await agent_client.health(agent_ip, container_name, do_token)
            details = health.get('details', [])
            raise Exception(f"Container crashed. Logs: {details}")
        
        stream('Test run OK.')
        yield sse_log(stream._logs[-1])
        
        await agent_client.remove_container(agent_ip, container_name, do_token)
        
        db_droplet = await droplets.get(db, droplet_id)
        if not db_droplet:
            raise Exception("Droplet not found in DB")
        
        stream('Powering off droplet...')
        yield sse_log(stream._logs[-1])
        
        async with AsyncDOClient(api_token=do_token) as client:
            await client.power_off_droplet(db_droplet.do_droplet_id)
            await asyncio.sleep(10)
            
            stream(f'Creating snapshot: {snapshot_name}...')
            yield sse_log(stream._logs[-1])
            await client.create_snapshot_from_droplet(db_droplet.do_droplet_id, name=snapshot_name)
            
            snap_list = await client.list_snapshots()
            do_snapshot = next((s for s in snap_list if s.name == snapshot_name), None)
            do_snapshot_id = do_snapshot.id if do_snapshot else None
            size_gb = do_snapshot.size_gigabytes if do_snapshot else 0
            
            if not do_snapshot_id:
                raise Exception("Snapshot not found after creation")
            
            stream('Cleaning up...')
            yield sse_log(stream._logs[-1])
            await client.delete_droplet(db_droplet.do_droplet_id, force=True)
        
        await droplets.delete(db, droplet_id)
        droplet_id = None
        
        snap = await snapshots.create(db, {
            'workspace_id': user_id,
            'do_snapshot_id': str(do_snapshot_id),
            'name': snapshot_name,
            'region': region,
            'size_gigabytes': size_gb,
            'is_base': False,
            'is_managed': is_managed,
        })
        
        stream(f'Custom snapshot ready: {snapshot_name}')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, snap.id)
    
    except Exception as e:
        if droplet_id:
            try:
                d = await droplets.get(db, droplet_id)
                if d:
                    async with AsyncDOClient(api_token=do_token) as client:
                        await client.delete_droplet(d.do_droplet_id, force=True)
                    await droplets.delete(db, droplet_id)
            except:
                pass
        
        stream(f'Error: {e}')
        yield sse_log(stream._logs[-1], 'error')
        yield sse_complete(False, '', str(e))


# =============================================================================
# Template Creation (internal)
# =============================================================================

async def _create_template(
    client: AsyncDOClient, stream: StreamContext, user_id: str,
    region: str, size: str, images: List[str], do_token: str,
    result: Dict[str, Any],
    cleanup_on_failure: bool = True,
) -> AsyncIterator[str]:
    """Create template snapshot: Docker + nginx + SSL + git + images."""
    
    template_droplet_id = None
    droplet_ip = None
    ssh_key_path = os.environ.get('SSH_PRIVATE_KEY_PATH', os.path.expanduser('~/.ssh/id_ed25519'))
    
    try:
        stream('Setting up SSH key...')
        yield sse_log(stream._logs[-1])
        
        ssh_key_id, ssh_messages = await _ensure_ssh_key(client, ssh_key_path)
        for msg, level in ssh_messages:
            stream(f'  {msg}')
            yield sse_log(stream._logs[-1], level)
        
        if not ssh_key_id:
            raise Exception(f'SSH key setup failed. Ensure private key exists at {ssh_key_path}')
        
        stream(f'SSH key ready (ID: {ssh_key_id})')
        yield sse_log(stream._logs[-1])
        
        stream(f'Ensuring VPC in {region}...')
        yield sse_log(stream._logs[-1])
        
        vpc_uuid = await client.ensure_vpc(region=region)
        
        stream(f'VPC ready: {vpc_uuid[:8]}...')
        yield sse_log(stream._logs[-1])
        
        stream('Creating temp droplet for template...')
        yield sse_log(stream._logs[-1])
        
        droplet = await client.create_droplet(
            name='temp-template', region=region, size=size,
            image='ubuntu-24-04-x64',
            tags=[f'user:{user_id}', 'temp-snapshot'],
            ssh_keys=[str(ssh_key_id)],
            vpc_uuid=vpc_uuid,
            auto_vpc=False,
            wait=False,
        )
        
        stream(f'Droplet created: {droplet.id}')
        yield sse_log(stream._logs[-1])
        
        template_droplet_id = droplet.id
        
        droplet_ip, ip_messages = await _wait_for_ip(client, template_droplet_id)
        for msg, level in ip_messages:
            stream(msg)
            yield sse_log(stream._logs[-1], level)
        
        if not droplet_ip:
            raise Exception('Timeout waiting for IP')
        
        stream(f'Droplet ready at {droplet_ip}')
        yield sse_log(stream._logs[-1])
        
        stream('Waiting for SSH...')
        yield sse_log(stream._logs[-1])
        
        ssh_ready = False
        for attempt in range(6):
            await asyncio.sleep(10)
            try:
                async with asyncssh.connect(droplet_ip, username='root', known_hosts=None, 
                                           client_keys=[ssh_key_path], connect_timeout=10) as test_conn:
                    await test_conn.run('echo ok', check=True)
                    ssh_ready = True
                    break
            except Exception as e:
                stream(f'  SSH not ready yet ({attempt+1}/6): {type(e).__name__}')
                yield sse_log(stream._logs[-1])
        
        if not ssh_ready:
            raise Exception('SSH connection timeout after 60s')
        
        stream('SSH connected')
        yield sse_log(stream._logs[-1])
        
        async with asyncssh.connect(droplet_ip, username='root', known_hosts=None, client_keys=[ssh_key_path]) as conn:
            stream('Waiting for cloud-init to complete...')
            yield sse_log(stream._logs[-1])
            await conn.run('cloud-init status --wait', check=False)
            
            for attempt in range(6):
                result_lock = await conn.run('fuser /var/lib/dpkg/lock-frontend 2>/dev/null', check=False)
                if result_lock.returncode != 0:
                    break
                stream(f'  Waiting for apt lock... ({attempt+1}/6)')
                yield sse_log(stream._logs[-1])
                await asyncio.sleep(10)
            
            stream('Updating package lists...')
            yield sse_log(stream._logs[-1])
            await conn.run('DEBIAN_FRONTEND=noninteractive apt-get update -q', check=True)
            
            stream('Installing Docker...')
            yield sse_log(stream._logs[-1])
            await conn.run('curl -fsSL https://get.docker.com | sh', check=True)
            await conn.run('systemctl enable docker && systemctl start docker', check=True)
            
            stream('Installing nginx...')
            yield sse_log(stream._logs[-1])
            await conn.run('DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx', check=True)
            await conn.run('systemctl enable nginx', check=True)
            
            stream('Installing git...')
            yield sse_log(stream._logs[-1])
            await conn.run('DEBIAN_FRONTEND=noninteractive apt-get install -y -q git', check=True)
            
            stream('Uploading SSL certificates...')
            yield sse_log(stream._logs[-1])
            
            cert_dir = os.path.dirname(os.path.dirname(__file__))
            with open(os.path.join(cert_dir, 'certificate.pem'), encoding='utf-8') as f:
                cert_pem = f.read()
            with open(os.path.join(cert_dir, 'certificate.key'), encoding='utf-8') as f:
                cert_key = f.read()
            
            await conn.run('mkdir -p /etc/nginx', check=True)
            await conn.run(f"cat > /etc/nginx/certificate.pem << 'EOF'\n{cert_pem}\nEOF", check=True)
            await conn.run(f"cat > /etc/nginx/certificate.key << 'EOF'\n{cert_key}\nEOF", check=True)
            await conn.run('chmod 600 /etc/nginx/certificate.key', check=True)
            
            # Ubuntu 24.04: use apt package to avoid pip/system conflicts
            # pip3 install flask fails because blinker is system-managed
            stream('Installing Python dependencies (python3-flask via apt)...')
            yield sse_log(stream._logs[-1])
            
            cmd_result = await conn.run('DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-flask 2>&1', check=False)
            if cmd_result.returncode != 0:
                output = cmd_result.stdout[:200] if cmd_result.stdout else "no output"
                stream(f'  FAILED: {output}')
                yield sse_log(stream._logs[-1], 'error')
                raise Exception(f'apt-get python3-flask failed: {output}')
            
            stream('  python3-flask installed OK')
            yield sse_log(stream._logs[-1])
            
            await conn.run('mkdir -p /data', check=True)
            await conn.run('mkdir -p /opt/node_agent', check=True)
            
            stream(f'Pulling {len(images)} Docker images...')
            yield sse_log(stream._logs[-1])
            
            for i, img in enumerate(images):
                stream(f'  Pulling {img} ({i+1}/{len(images)})...')
                yield sse_log(stream._logs[-1])
                await conn.run(f'docker pull {img}', check=True)
            
            stream('All images pulled.')
            yield sse_log(stream._logs[-1])
            
            stream('Cleaning up...')
            yield sse_log(stream._logs[-1])
            await conn.run('apt-get clean && rm -rf /var/lib/apt/lists/*', check=True)
        
        stream('Powering off template droplet...')
        yield sse_log(stream._logs[-1])
        await client.power_off_droplet(template_droplet_id)
        await asyncio.sleep(10)
        
        stream('Creating template snapshot...')
        yield sse_log(stream._logs[-1])
        await client.create_snapshot_from_droplet(template_droplet_id, name=TEMPLATE_SNAPSHOT_NAME)
        
        snap_list = await client.list_snapshots()
        snapshot = next((s for s in snap_list if s.name == TEMPLATE_SNAPSHOT_NAME), None)
        
        stream('Cleaning up template droplet...')
        yield sse_log(stream._logs[-1])
        await client.delete_droplet(template_droplet_id, force=True)
        template_droplet_id = None
        
        stream('Template created.')
        yield sse_log(stream._logs[-1])
        
        result['template_id'] = snapshot.id if snapshot else None
    
    except Exception as e:
        error_msg = str(e)
        stream(f'Template creation failed: {error_msg}')
        yield sse_log(stream._logs[-1], 'error')
        
        if template_droplet_id:
            if cleanup_on_failure:
                try:
                    await client.delete_droplet(template_droplet_id, force=True)
                    stream('Droplet deleted')
                    yield sse_log(stream._logs[-1])
                except:
                    pass
            else:
                stream(f'DROPLET KEPT FOR DEBUGGING: ssh root@{droplet_ip}')
                yield sse_log(stream._logs[-1])
        
        yield sse_complete(False, '', f'Template creation failed: {error_msg}')


# =============================================================================
# Helpers
# =============================================================================

async def _ensure_ssh_key(client: AsyncDOClient, private_key_path: str) -> tuple:
    """
    Ensure SSH key exists locally and is registered with DO.
    
    Returns:
        (ssh_key_id, messages) - ssh_key_id is None on failure
        messages is a list of (message, level) tuples
    """
    import subprocess
    from pathlib import Path
    
    messages = []
    
    private_key_path = Path(private_key_path).expanduser()
    public_key_path = Path(str(private_key_path) + ".pub")
    
    if not private_key_path.exists():
        messages.append((f'Generating SSH key at {private_key_path}...', 'info'))
        private_key_path.parent.mkdir(mode=0o700, exist_ok=True)
        try:
            subprocess.run([
                "ssh-keygen", "-t", "ed25519",
                "-f", str(private_key_path),
                "-N", "", "-C", "deployer@deploy-api"
            ], capture_output=True, check=True)
            private_key_path.chmod(0o600)
            messages.append(('SSH key generated', 'info'))
        except Exception as e:
            messages.append((f'Failed to generate SSH key: {e}', 'error'))
            return None, messages
    
    if not public_key_path.exists():
        messages.append((f'Public key not found at {public_key_path}', 'error'))
        return None, messages
    
    public_key = public_key_path.read_text().strip()
    key_hash = hashlib.sha256(public_key.encode()).hexdigest()[:8]
    
    existing_keys = await client.list_ssh_keys()
    for key in existing_keys:
        if key.public_key.strip() == public_key:
            messages.append((f'Using existing SSH key (ID: {key.id})', 'info'))
            return key.id, messages
    
    key_name = f"deployer-{key_hash}"
    try:
        new_key = await client.add_ssh_key(key_name, public_key)
        messages.append((f'Registered new SSH key: {key_name}', 'info'))
        return new_key.id, messages
    except Exception as e:
        messages.append((f'Failed to register SSH key with DO: {e}', 'error'))
        return None, messages


async def _wait_for_ip(client: AsyncDOClient, droplet_id: int, timeout: int = 60) -> tuple:
    """
    Wait for droplet to get an IP address.
    
    Returns:
        (ip, messages) - ip is None on timeout
        messages is list of (message, level) tuples
    """
    messages = [('Waiting for droplet IP...', 'info')]
    
    for i in range(timeout // 2):
        await asyncio.sleep(2)
        info = await client.get_droplet(droplet_id)
        if info and info.ip:
            return info.ip, messages
        if i % 5 == 4:
            messages.append((f'Still waiting for IP... ({i*2}s)', 'info'))
    
    messages.append(('Timeout waiting for IP', 'error'))
    return None, messages


async def _check_agent_health(ip: str, api_key: str, retries: int = 5) -> tuple:
    """Check if node agent is responding."""
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f'http://{ip}:9999/ping',
                    headers={'X-API-Key': api_key},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        version = data.get('version', 'unknown')
                        return True, f'v{version} responding'
                    else:
                        return False, f'HTTP {resp.status}'
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            if attempt == retries - 1:
                return False, f'{type(e).__name__}: {e}'
        
        await asyncio.sleep(3)
    
    return False, 'Connection timeout'


async def _get_agent_diagnostics(ip: str, ssh_key_path: str) -> Optional[str]:
    """Get agent diagnostics via SSH."""
    try:
        async with asyncssh.connect(ip, username='root', known_hosts=None, 
                                   client_keys=[ssh_key_path], connect_timeout=10) as conn:
            result = await conn.run(
                'systemctl status node-agent --no-pager 2>&1 | head -20; '
                'echo "---"; '
                'journalctl -u node-agent -n 30 --no-pager 2>&1',
                check=False
            )
            return result.stdout if result.stdout else None
    except Exception as e:
        return f'SSH failed: {e}'


# =============================================================================
# Delete / List
# =============================================================================

async def delete_snapshot(db, snapshot_id: str, do_token: str) -> Dict[str, Any]:
    """Delete snapshot from DO and DB."""
    snap = await snapshots.get(db, snapshot_id)
    if not snap:
        return {'error': 'Snapshot not found'}
    
    async with AsyncDOClient(api_token=do_token) as client:
        try:
            await client.delete_snapshot(snap.do_snapshot_id)
        except:
            pass
    
    await snapshots.delete(db, snapshot_id)
    return {'status': 'deleted', 'name': snap.name}


async def list_base_images() -> List[Dict[str, Any]]:
    """Return list of available base images with ports."""
    return [{'image': img, 'port': port} for img, port in BASE_IMAGES.items()]

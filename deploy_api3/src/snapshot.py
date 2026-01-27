# =============================================================================
# src/snapshot.py
# =============================================================================
"""Snapshot provisioning with template caching."""

import os
import hmac
import hashlib
import asyncio
from typing import Dict, Any, List, AsyncIterator
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
    images: List[str] = None, size: str = 's-1vcpu-1gb'
) -> AsyncIterator[str]:
    """
    Create base snapshot from template (creating template if needed).
    
    Template: Docker + nginx + SSL + git + images (no agent, no firewall)
    Base: Template + agent + firewall + user restrictions
    """
    stream = StreamContext()
    do_droplet_id = None
    images = images or list(BASE_IMAGES.keys())
    
    try:
        async with AsyncDOClient(api_token=do_token) as client:
            
            # =================================================================
            # 1. Get or create template
            # =================================================================
            existing = await client.list_snapshots()
            template = next((s for s in existing if s.get('name') == TEMPLATE_SNAPSHOT_NAME), None)
            
            if template:
                template_id = template['id']
            else:
                result = {}
                async for event in _create_template(
                    client, stream, user_id, region, size, images, do_token, result
                ):
                    yield event
                template_id = result['template_id']
            
            # =================================================================
            # 2. Create base from template
            # =================================================================
            stream('Creating temp droplet from template...')
            yield sse_log(stream._logs[-1])
            
            droplet_result = await client.create_droplet(
                name='temp-base', region=region, size=size,
                image=template_id,
                tags=[f'user:{user_id}', 'temp-snapshot'],
            )
            do_droplet_id = droplet_result['id']
            
            # Wait for IP
            ip = await _wait_for_ip(client, do_droplet_id, stream)
            yield sse_log(stream._logs[-1])
            
            if not ip:
                raise Exception('Timeout waiting for IP')
            
            stream(f'Droplet ready at {ip}')
            yield sse_log(stream._logs[-1])
            
            # Wait for SSH
            stream('Waiting for SSH...')
            yield sse_log(stream._logs[-1])
            await asyncio.sleep(20)
            
            # Install agent + firewall + user restrictions
            async with asyncssh.connect(ip, username='root', known_hosts=None) as conn:
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
                with open(agent_path) as f:
                    agent_code = f.read()
                
                await conn.run(f"cat > /opt/node_agent/agent.py << 'AGENT_EOF'\n{agent_code}\nAGENT_EOF", check=True)
                await conn.run('chown nodeagent:nodeagent /opt/node_agent/agent.py', check=True)
                
                # Systemd service
                stream('Creating systemd service...')
                yield sse_log(stream._logs[-1])
                
                api_key = hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()
                
                service_content = f'''[Unit]
Description=Node Agent
After=network.target docker.service

[Service]
Type=simple
User=nodeagent
Group=nodeagent
Environment="NODE_AGENT_API_KEY={api_key}"
ExecStart=/usr/bin/python3 /opt/node_agent/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target'''
                
                await conn.run(f"cat > /etc/systemd/system/node-agent.service << 'EOF'\n{service_content}\nEOF", check=True)
                await conn.run('systemctl daemon-reload && systemctl enable node-agent', check=True)
                
                # Firewall
                stream('Configuring firewall...')
                yield sse_log(stream._logs[-1])
                
                await conn.run('ufw --force reset', check=True)
                await conn.run('ufw default deny incoming', check=True)
                await conn.run('ufw default allow outgoing', check=True)
                await conn.run('ufw allow 443/tcp', check=True)
                await conn.run('ufw allow 9999/tcp', check=True)
                
                for admin_ip in os.environ.get('ADMIN_IPS', '').split(','):
                    if admin_ip.strip():
                        await conn.run(f'ufw allow from {admin_ip.strip()} to any port 22', check=True)
                
                await conn.run('ufw --force enable', check=True)
            
            # Power off
            stream('Powering off droplet...')
            yield sse_log(stream._logs[-1])
            await client.power_off_droplet(do_droplet_id)
            await asyncio.sleep(10)
            
            # Snapshot
            stream('Creating snapshot...')
            yield sse_log(stream._logs[-1])
            snapshot = await client.create_snapshot(do_droplet_id, name='base')
            do_snapshot_id = snapshot['id']
            
            # Cleanup temp droplet
            stream('Cleaning up temp droplet...')
            yield sse_log(stream._logs[-1])
            await client.delete_droplet(do_droplet_id)
            do_droplet_id = None
            
            # Save to DB
            snap = await snapshots.create(db, {
                'workspace_id': user_id,
                'do_snapshot_id': str(do_snapshot_id),
                'name': 'base',
                'region': region,
                'size_gigabytes': snapshot.get('size_gigabytes'),
                'agent_version': AGENT_VERSION,
                'is_base': True,
            })
            
            stream('Base snapshot ready!')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, snap['id'])
    
    except Exception as e:
        if do_droplet_id:
            try:
                async with AsyncDOClient(api_token=do_token) as client:
                    await client.delete_droplet(do_droplet_id)
            except:
                pass
        
        stream(f'Error: {e}')
        yield sse_log(stream._logs[-1], 'error')
        yield sse_complete(False, '', str(e))


# =============================================================================
# Custom Snapshot Creation
# =============================================================================

async def create_custom_snapshot(
    db, user_id: str, do_token: str,
    # Source:
    git_repos: List[Dict] = None,
    source_zips: Dict[str, bytes] = None,
    dockerfile_content: str = None,
    # Options:
    snapshot_name: str = None,
    region: str = 'lon1',
    size: str = 's-1vcpu-1gb',
    base_snapshot_id: str = None,
    test_env_variables: List[str] = None,
) -> AsyncIterator[str]:
    """
    Create a custom snapshot with image baked in.
    
    1. Create temp droplet from base
    2. Build image from git/zips
    3. Test run (verify it starts)
    4. Snapshot droplet
    5. Cleanup
    
    Image always named 'base'. Use in Dockerfile: FROM local/base
    """
    stream = StreamContext()
    droplet = None
    droplet_id = None
    image_name = 'base'
    
    try:
        # Validate
        if not git_repos and not source_zips:
            raise Exception('Need git_repos or source_zips')
        
        snapshot_name = snapshot_name or f'custom-{user_id[:6]}'
        
        # Get base snapshot
        if not base_snapshot_id:
            base = await snapshots.get_by_name(db, user_id, 'base')
            if not base:
                raise Exception("No base snapshot. Run create_base_snapshot first.")
            base_snapshot_id = base['id']
        
        # 1. Create temp droplet
        stream('Creating temp droplet...')
        yield sse_log(stream._logs[-1])
        
        from .droplet import create_droplet
        droplet = await create_droplet(db, user_id, base_snapshot_id, region, size, do_token)
        if droplet.get('error'):
            raise Exception(f"Droplet creation failed: {droplet['error']}")
        
        droplet_id = droplet['id']
        droplet_ip = droplet['ip']
        stream(f'Droplet ready at {droplet_ip}')
        yield sse_log(stream._logs[-1])
        
        # 2. Build image
        stream('Building image...')
        yield sse_log(stream._logs[-1])
        
        result = await agent_client.build_image(
            droplet_ip, image_name, do_token,
            git_repos=git_repos,
            source_zips=source_zips,
            dockerfile_content=dockerfile_content
        )
        
        if result.get('status') == 'failed':
            raise Exception(f"Build failed: {result.get('error')}")
        
        stream(f'Image built: {image_name}')
        yield sse_log(stream._logs[-1])
        
        # 3. Test run
        stream('Test run...')
        yield sse_log(stream._logs[-1])
        
        container_name = 'test-run'
        
        result = await agent_client.start_container(
            droplet_ip, container_name, image_name,
            test_env_variables or [], 8000, 19999, do_token
        )
        if result.get('error'):
            raise Exception(f"Test start failed: {result['error']}")
        
        await asyncio.sleep(5)
        status = await agent_client.container_status(droplet_ip, container_name, do_token)
        
        if not status.get('running'):
            health = await agent_client.health(droplet_ip, container_name, do_token)
            details = health.get('details', [])
            raise Exception(f"Container crashed. Logs: {details}")
        
        stream('Test run OK.')
        yield sse_log(stream._logs[-1])
        
        await agent_client.remove_container(droplet_ip, container_name, do_token)
        
        # 4. Power off and snapshot
        stream('Powering off droplet...')
        yield sse_log(stream._logs[-1])
        
        async with AsyncDOClient(api_token=do_token) as client:
            await client.power_off_droplet(droplet['do_droplet_id'])
            await asyncio.sleep(10)
            
            stream(f'Creating snapshot: {snapshot_name}...')
            yield sse_log(stream._logs[-1])
            snapshot = await client.create_snapshot(droplet['do_droplet_id'], name=snapshot_name)
            do_snapshot_id = snapshot['id']
            
            # 5. Cleanup
            stream('Cleaning up...')
            yield sse_log(stream._logs[-1])
            await client.delete_droplet(droplet['do_droplet_id'])
        
        await droplets.delete(db, droplet_id)
        droplet_id = None
        
        # Save snapshot
        snap = await snapshots.create(db, {
            'workspace_id': user_id,
            'do_snapshot_id': str(do_snapshot_id),
            'name': snapshot_name,
            'region': region,
            'size_gigabytes': snapshot.get('size_gigabytes'),
            'is_base': False,
        })
        
        stream(f'Custom snapshot ready: {snapshot_name}')
        stream('Use in Dockerfile: FROM local/base')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, snap['id'])
    
    except Exception as e:
        # Cleanup on error
        if droplet_id:
            try:
                d = await droplets.get(db, droplet_id)
                if d:
                    async with AsyncDOClient(api_token=do_token) as client:
                        await client.delete_droplet(d['do_droplet_id'])
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
    result: Dict[str, Any]
) -> AsyncIterator[str]:
    """Create template snapshot: Docker + nginx + SSL + git + images. No agent, no firewall."""
    
    template_droplet_id = None
    
    try:
        # Create droplet from Ubuntu
        stream('Creating temp droplet for template...')
        yield sse_log(stream._logs[-1])
        
        droplet = await client.create_droplet(
            name='temp-template', region=region, size=size,
            image='ubuntu-24-04-x64',
            tags=[f'user:{user_id}', 'temp-snapshot'],
        )
        template_droplet_id = droplet['id']
        
        # Wait for IP
        ip = await _wait_for_ip(client, template_droplet_id, stream)
        yield sse_log(stream._logs[-1])
        
        if not ip:
            raise Exception('Timeout waiting for IP')
        
        stream(f'Droplet ready at {ip}')
        yield sse_log(stream._logs[-1])
        
        # Wait for SSH
        stream('Waiting for SSH...')
        yield sse_log(stream._logs[-1])
        await asyncio.sleep(30)
        
        # SSH and install everything
        async with asyncssh.connect(ip, username='root', known_hosts=None) as conn:
            # Update system
            stream('Updating system packages...')
            yield sse_log(stream._logs[-1])
            await conn.run('apt-get update && apt-get upgrade -y', check=True)
            
            # Docker
            stream('Installing Docker...')
            yield sse_log(stream._logs[-1])
            await conn.run('curl -fsSL https://get.docker.com | sh', check=True)
            await conn.run('systemctl enable docker && systemctl start docker', check=True)
            
            # Nginx
            stream('Installing nginx...')
            yield sse_log(stream._logs[-1])
            await conn.run('apt-get install -y nginx', check=True)
            await conn.run('systemctl enable nginx', check=True)
            
            # Git
            stream('Installing git...')
            yield sse_log(stream._logs[-1])
            await conn.run('apt-get install -y git', check=True)
            
            # SSL certificates
            stream('Uploading SSL certificates...')
            yield sse_log(stream._logs[-1])
            
            cert_dir = os.path.dirname(os.path.dirname(__file__))
            with open(os.path.join(cert_dir, 'certificate.pem')) as f:
                cert_pem = f.read()
            with open(os.path.join(cert_dir, 'certificate.key')) as f:
                cert_key = f.read()
            
            await conn.run('mkdir -p /etc/nginx', check=True)
            await conn.run(f"cat > /etc/nginx/certificate.pem << 'EOF'\n{cert_pem}\nEOF", check=True)
            await conn.run(f"cat > /etc/nginx/certificate.key << 'EOF'\n{cert_key}\nEOF", check=True)
            await conn.run('chmod 600 /etc/nginx/certificate.key', check=True)
            
            # Python for agent
            stream('Installing Python dependencies...')
            yield sse_log(stream._logs[-1])
            await conn.run('apt-get install -y python3-pip', check=True)
            await conn.run('pip3 install flask --break-system-packages', check=True)
            
            # Create directories
            await conn.run('mkdir -p /data', check=True)
            await conn.run('mkdir -p /opt/node_agent', check=True)
            
            # Pull Docker images
            stream(f'Pulling {len(images)} Docker images...')
            yield sse_log(stream._logs[-1])
            
            for i, img in enumerate(images):
                stream(f'  Pulling {img} ({i+1}/{len(images)})...')
                yield sse_log(stream._logs[-1])
                await conn.run(f'docker pull {img}', check=True)
            
            stream('All images pulled.')
            yield sse_log(stream._logs[-1])
            
            # Cleanup apt
            stream('Cleaning up...')
            yield sse_log(stream._logs[-1])
            await conn.run('apt-get clean && rm -rf /var/lib/apt/lists/*', check=True)
        
        # Power off
        stream('Powering off template droplet...')
        yield sse_log(stream._logs[-1])
        await client.power_off_droplet(template_droplet_id)
        await asyncio.sleep(10)
        
        # Create snapshot
        stream('Creating template snapshot...')
        yield sse_log(stream._logs[-1])
        snapshot = await client.create_snapshot(template_droplet_id, name=TEMPLATE_SNAPSHOT_NAME)
        
        # Delete temp droplet
        stream('Cleaning up template droplet...')
        yield sse_log(stream._logs[-1])
        await client.delete_droplet(template_droplet_id)
        template_droplet_id = None
        
        stream('Template created.')
        yield sse_log(stream._logs[-1])
        
        # Return via mutable container
        result['template_id'] = snapshot['id']
    
    except Exception as e:
        if template_droplet_id:
            try:
                await client.delete_droplet(template_droplet_id)
            except:
                pass
        raise


# =============================================================================
# Helpers
# =============================================================================

async def _wait_for_ip(client: AsyncDOClient, droplet_id: str, stream: StreamContext, timeout: int = 60) -> str:
    """Wait for droplet to get an IP address."""
    stream('Waiting for droplet IP...')
    
    for i in range(timeout // 2):
        await asyncio.sleep(2)
        info = await client.get_droplet(droplet_id)
        for net in info.get('networks', {}).get('v4', []):
            if net.get('type') == 'public':
                return net.get('ip_address')
        if i % 5 == 4:
            stream(f'Still waiting for IP... ({i*2}s)')
    
    return None


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
            await client.delete_snapshot(snap['do_snapshot_id'])
        except:
            pass
    
    await snapshots.delete(db, snapshot_id)
    return {'status': 'deleted', 'name': snap.get('name')}


async def list_base_images() -> List[Dict[str, Any]]:
    """Return list of available base images with ports."""
    return [{'image': img, 'port': port} for img, port in BASE_IMAGES.items()]


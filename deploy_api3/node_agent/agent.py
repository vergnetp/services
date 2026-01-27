"""
Node Agent - Flask app that runs ON each droplet.
Serialized and embedded into snapshot via cloud-init.

Endpoints:
- GET  /ping                           - Agent health check
- POST /upload                         - Receive Docker image
- POST /start_container                - Start a container
- POST /remove_container               - Stop and remove container
- GET  /health?container_name=xxx      - Health check with log parsing + TCP ping
- GET  /containers/<name>/status       - Get container status
- POST /containers/<name>/restart      - Restart container
- POST /configure_nginx                - Configure nginx upstream
"""

import os
import re
import socket
import subprocess
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# Simple API key auth (derived from DO token during snapshot creation)
API_KEY = os.environ.get('NODE_AGENT_API_KEY', 'dev-key')


def require_auth(f):
    """Simple API key authentication decorator."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-API-Key')
        if key != API_KEY:
            return jsonify({'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# =============================================================================
# PING
# =============================================================================

@app.route('/ping', methods=['GET'])
@require_auth
def ping():
    """Agent health check."""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()})


# =============================================================================
# DOCKER IMAGE UPLOAD
# =============================================================================

@app.route('/upload', methods=['POST'])
@require_auth
def upload():
    """
    Receive Docker image as stream and load it.
    Query params: name (image name)
    Body: raw image bytes (tar)
    """
    image_name = request.args.get('name')
    if not image_name:
        return jsonify({'error': 'name required'}), 400
    
    try:
        # Stream to temp file to avoid memory issues
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as f:
            for chunk in request.stream:
                f.write(chunk)
            temp_path = f.name
        
        # Load image
        result = subprocess.run(
            ['docker', 'load', '-i', temp_path],
            capture_output=True, text=True
        )
        
        os.unlink(temp_path)
        
        if result.returncode != 0:
            return jsonify({'error': result.stderr}), 500
        
        return jsonify({'status': 'loaded', 'image': image_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# CONTAINER MANAGEMENT
# =============================================================================

@app.route('/start_container', methods=['POST'])
@require_auth
def start_container():
    """
    Start a container.
    JSON body: container_name, image_name, env_variables[], container_port, host_port
    """
    data = request.json
    container_name = data.get('container_name')
    image_name = data.get('image_name')
    env_variables = data.get('env_variables', [])
    container_port = data.get('container_port')
    host_port = data.get('host_port')
    volumes = data.get('volumes', ['/data:/app/data'])
    
    if not all([container_name, image_name, container_port, host_port]):
        return jsonify({'error': 'missing required fields'}), 400
    
    try:
        # Build docker run command
        cmd = [
            'docker', 'run', '-d',
            '--name', container_name,
            '-p', f'{host_port}:{container_port}',
            '-v', '/data:/app/data',
            '--restart', 'unless-stopped',
        ]
        
        # Add environment variables
        for env in env_variables:
            cmd.extend(['-e', env])
        
        # Add custom volumes
        for vol in volumes:
            if vol != '/data:/app/data':  # Already added
                cmd.extend(['-v', vol])
        
        cmd.append(image_name)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return jsonify({'error': result.stderr}), 500
        
        return jsonify({
            'status': 'started',
            'container_name': container_name,
            'container_id': result.stdout.strip()[:12]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/remove_container', methods=['POST'])
@require_auth
def remove_container():
    """
    Stop and remove a container.
    JSON body or query param: container_name
    """
    container_name = request.args.get('container_name') or (request.json or {}).get('container_name')
    if not container_name:
        return jsonify({'error': 'container_name required'}), 400
    
    try:
        # Stop
        subprocess.run(['docker', 'stop', container_name], capture_output=True)
        # Remove
        subprocess.run(['docker', 'rm', '-f', container_name], capture_output=True)
        
        return jsonify({'status': 'removed', 'container_name': container_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/containers/<container_name>/restart', methods=['POST'])
@require_auth
def restart_container(container_name):
    """Restart a container."""
    try:
        result = subprocess.run(
            ['docker', 'restart', container_name],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return jsonify({'error': result.stderr}), 500
        
        return jsonify({'status': 'restarted', 'container_name': container_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/containers/<container_name>/status', methods=['GET'])
@require_auth
def container_status(container_name):
    """Get container status via docker inspect."""
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format',
             '{{.State.Status}}|{{.State.Health.Status}}|{{.State.Running}}',
             container_name],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return jsonify({'error': 'not_found'}), 404
        
        parts = result.stdout.strip().split('|')
        state = parts[0] if parts else 'unknown'
        health = parts[1] if len(parts) > 1 else 'none'
        running = parts[2] == 'true' if len(parts) > 2 else False
        
        return jsonify({
            'container_name': container_name,
            'state': state,
            'health_status': health,
            'running': running
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# HEALTH CHECK (with log parsing + TCP ping)
# =============================================================================

def parse_logs_for_errors(container_name, max_errors=5):
    """
    Parse docker logs for errors.
    Returns list of up to max_errors error messages.
    """
    try:
        result = subprocess.run(
            ['docker', 'logs', '--tail', '200', container_name],
            capture_output=True, text=True
        )
        
        logs = result.stdout + result.stderr
        
        # Look for common error patterns
        error_patterns = [
            r'(?i)error[:\s].*',
            r'(?i)exception[:\s].*',
            r'(?i)failed[:\s].*',
            r'(?i)traceback.*',
            r'(?i)fatal[:\s].*',
            r'(?i)\[error\].*',
            r'(?i)panic[:\s].*',
        ]
        
        errors = []
        for line in logs.split('\n'):
            for pattern in error_patterns:
                if re.search(pattern, line):
                    # Clean and truncate
                    clean_line = line.strip()[:200]
                    if clean_line and clean_line not in errors:
                        errors.append(clean_line)
                        if len(errors) >= max_errors:
                            return errors
                    break
        
        return errors
    except Exception:
        return []


def tcp_ping(host, port, timeout=5):
    """
    TCP ping to check if port is reachable.
    Returns True if connection successful.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def get_container_host_port(container_name):
    """Get the host port mapped to the container."""
    try:
        result = subprocess.run(
            ['docker', 'port', container_name],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return None
        
        # Parse output like "8000/tcp -> 0.0.0.0:12345"
        for line in result.stdout.strip().split('\n'):
            if '->' in line:
                # Get the host port
                parts = line.split('->')
                if len(parts) == 2:
                    host_part = parts[1].strip()
                    if ':' in host_part:
                        port_str = host_part.split(':')[-1]
                        return int(port_str)
        return None
    except Exception:
        return None


def get_container_info(container_name):
    """Get container info from docker inspect."""
    try:
        result = subprocess.run(
            ['docker', 'inspect', '--format',
             '{{.Id}}|{{.State.Status}}|{{.State.StartedAt}}|{{.Config.Image}}',
             container_name],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return None
        
        parts = result.stdout.strip().split('|')
        return {
            'id': parts[0][:12] if parts else None,
            'status': parts[1] if len(parts) > 1 else None,
            'started_at': parts[2] if len(parts) > 2 else None,
            'image': parts[3] if len(parts) > 3 else None,
        }
    except Exception:
        return None


@app.route('/health', methods=['GET'])
@require_auth
def health():
    """
    Health check for a container.
    
    Flow (per pseudo code):
    1. Parse logs for errors (up to 5)
    2. Check if container is running
    3. Get host port and TCP ping
    4. Return status based on results
    
    Returns:
        {'status': 'healthy|unhealthy|degraded', 'reason': '...', 'details': [...], 'container_info': {...}}
    """
    container_name = request.args.get('container_name')
    if not container_name:
        return jsonify({'error': 'container_name required'}), 400
    
    # 1. Parse logs for errors
    errors = parse_logs_for_errors(container_name)
    
    # 2. Check if container is running
    container_info = get_container_info(container_name)
    
    if not container_info or container_info.get('status') != 'running':
        return jsonify({
            'status': 'unhealthy',
            'reason': 'not running',
            'details': errors,
            'container_info': container_info
        })
    
    # 3. Get host port and TCP ping
    host_port = get_container_host_port(container_name)
    
    if host_port:
        reachable = tcp_ping('127.0.0.1', host_port, timeout=5)
        
        if not reachable:
            return jsonify({
                'status': 'unhealthy',
                'reason': 'running but timed out',
                'details': errors,
                'container_info': container_info
            })
    
    # 4. Check for errors in logs
    if len(errors) > 0:
        return jsonify({
            'status': 'degraded',
            'reason': 'running fine but some errors can be found in the log',
            'details': errors,
            'container_info': container_info
        })
    
    return jsonify({
        'status': 'healthy',
        'container_info': container_info
    })


# =============================================================================
# NGINX CONFIGURATION
# =============================================================================

@app.route('/configure_nginx', methods=['POST'])
@require_auth
def configure_nginx():
    """
    Configure nginx upstream for a domain.
    JSON body: private_ips[], host_port, domain
    """
    data = request.json
    private_ips = data.get('private_ips', [])
    host_port = data.get('host_port')
    domain = data.get('domain')
    
    if not all([private_ips, host_port, domain]):
        return jsonify({'error': 'missing required fields'}), 400
    
    try:
        short = domain.replace('.digitalpixo.com', '')
        conf_path = f'/etc/nginx/sites-enabled/{short}.conf'
        
        # Build upstream servers list
        upstream_servers = '\n    '.join(f'server {ip}:{host_port};' for ip in private_ips)
        
        content = f'''upstream {short}_backend {{
    {upstream_servers}
}}

server {{
    listen 443 ssl;
    server_name {domain};
    
    ssl_certificate /etc/nginx/certificate.pem;
    ssl_certificate_key /etc/nginx/certificate.key;
    
    location / {{
        proxy_pass http://{short}_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}'''
        
        with open(conf_path, 'w') as f:
            f.write(content)
        
        # Reload nginx
        result = subprocess.run(['nginx', '-s', 'reload'], capture_output=True, text=True)
        
        if result.returncode != 0:
            return jsonify({'error': f'nginx reload failed: {result.stderr}'}), 500
        
        return jsonify({
            'status': 'configured',
            'domain': domain,
            'upstream_count': len(private_ips)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9999)

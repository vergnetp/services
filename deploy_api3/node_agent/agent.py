# =============================================================================
# node_agent/agent.py
# =============================================================================
"""
Node Agent - Flask app that runs ON each droplet.

Authentication:
- Accepts Bearer JWT tokens (short-lived, 10 min)
- JWT signed with HMAC-SHA256 using the long-lived API key
- Falls back to X-API-Key header for backwards compatibility

Endpoints:
- GET  /ping                    - Agent health check
- POST /upload                  - Receive Docker image tar
- POST /build                   - Build image from git/zips
- POST /start_container         - Start a container
- POST /remove_container        - Stop and remove container
- GET  /health                  - Health check with log parsing + TCP ping
- GET  /containers/<n>/status   - Get container status
- POST /containers/<n>/restart  - Restart container
- POST /configure_nginx         - Configure nginx upstream
"""

import os
import io
import re
import base64
import socket
import subprocess
import tempfile
import shutil
import zipfile
import hmac
import hashlib
import json
import time
from typing import Dict, Optional, Tuple
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

API_KEY = os.environ.get('NODE_AGENT_API_KEY', 'dev-key')
CHUNK_SIZE = 64 * 1024  # 64KB


# =============================================================================
# JWT Verification
# =============================================================================

def b64url_decode(data: str) -> bytes:
    """Decode base64url (handles missing padding)."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def verify_jwt(token: str, secret: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
    """
    Verify JWT token signature and expiry.
    
    Returns:
        (valid, payload, error) - valid=True if token is good
    """
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return False, None, "invalid token format"
        
        header_b64, payload_b64, signature_b64 = parts
        
        # Verify signature
        message = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
        actual_sig = b64url_decode(signature_b64)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return False, None, "invalid signature"
        
        # Decode payload
        payload = json.loads(b64url_decode(payload_b64).decode())
        
        # Check expiry
        exp = payload.get('exp', 0)
        if exp < time.time():
            return False, payload, "token expired"
        
        return True, payload, None
        
    except Exception as e:
        return False, None, f"token error: {e}"


def require_auth(f):
    """
    Authentication decorator supporting both JWT and legacy API key.
    
    Priority:
    1. Bearer token (JWT) in Authorization header
    2. X-API-Key header (legacy, for backwards compatibility)
    """
    from functools import wraps
    
    @wraps(f)
    def decorated(*args, **kwargs):
        # Try Bearer token first
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            valid, payload, error = verify_jwt(token, API_KEY)
            if valid:
                return f(*args, **kwargs)
            else:
                return jsonify({'error': 'unauthorized', 'detail': error}), 401
        
        # Fall back to X-API-Key (legacy)
        api_key = request.headers.get('X-API-Key')
        if api_key == API_KEY:
            return f(*args, **kwargs)
        
        return jsonify({'error': 'unauthorized', 'detail': 'missing or invalid credentials'}), 401
    
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
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as f:
            while True:
                chunk = request.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
            temp_path = f.name
        
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
# BUILD FROM GIT / ZIPS
# =============================================================================

def _repo_name_from_url(url: str) -> str:
    """Extract repo name from git URL."""
    name = url.rstrip('/').split('/')[-1]
    return name[:-4] if name.endswith('.git') else name


@app.route('/build', methods=['POST'])
@require_auth
def build():
    """
    Build Docker image from any combination of git repos and zips.
    
    JSON: {
        image_name: str,
        git_repos?: [{url, branch?, token?}, ...],
        zips?: {name: base64_data, ...},
        dockerfile_content?: str
    }
    
    All sources extracted as siblings in build dir:
    /tmp/build-xxx/
    ├── app/           ← from git (name from URL)
    ├── shared-lib/    ← from git
    ├── pkg/           ← from zip
    └── Dockerfile
    """
    build_dir = None
    
    try:
        build_dir = tempfile.mkdtemp(prefix='build-')
        data = request.json
        
        image_name = data.get('image_name')
        dockerfile_content = data.get('dockerfile_content')
        git_repos = data.get('git_repos', [])
        zips = data.get('zips', {})
        
        if not image_name:
            return jsonify({'error': 'image_name required'}), 400
        
        if not git_repos and not zips and not dockerfile_content:
            return jsonify({'error': 'need git_repos, zips, or dockerfile_content'}), 400
        
        # Clone git repos
        for repo in git_repos:
            url = repo.get('url')
            if not url:
                return jsonify({'error': 'git repo needs url'}), 400
            
            name = _repo_name_from_url(url)
            branch = repo.get('branch', 'main')
            token = repo.get('token')
            
            clone_url = url.replace('https://', f'https://{token}@') if token else url
            target_dir = os.path.join(build_dir, name)
            os.makedirs(target_dir, exist_ok=True)
            
            result = subprocess.run(
                ['git', 'clone', '--depth=1', '--branch', branch, clone_url, '.'],
                cwd=target_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                return jsonify({'error': f'Git clone failed for {name}: {result.stderr}'}), 500
        
        # Extract zips
        for name, data_b64 in zips.items():
            target_dir = os.path.join(build_dir, name)
            os.makedirs(target_dir, exist_ok=True)
            
            zip_bytes = base64.b64decode(data_b64)
            with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
                for member in zf.namelist():
                    if '..' in member or member.startswith('/'):
                        continue
                    zf.extract(member, target_dir)
            
            # Flatten single root folder
            contents = os.listdir(target_dir)
            if len(contents) == 1 and os.path.isdir(os.path.join(target_dir, contents[0])):
                inner = os.path.join(target_dir, contents[0])
                for item in os.listdir(inner):
                    shutil.move(os.path.join(inner, item), target_dir)
                os.rmdir(inner)
        
        # Write Dockerfile
        if dockerfile_content:
            with open(os.path.join(build_dir, 'Dockerfile'), 'w') as f:
                f.write(dockerfile_content)
        
        if not os.path.exists(os.path.join(build_dir, 'Dockerfile')):
            return jsonify({'error': 'No Dockerfile'}), 400
        
        # Build with resource limits
        result = subprocess.run(
            ['docker', 'build', '--memory=2g', '--cpu-quota=100000', '-t', image_name, '.'],
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode != 0:
            return jsonify({
                'status': 'failed',
                'error': result.stderr[-2000:],
                'logs': result.stdout[-2000:]
            }), 500
        
        return jsonify({
            'status': 'built',
            'image': image_name,
            'logs': result.stdout[-2000:]
        })
    
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Build timeout'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if build_dir:
            shutil.rmtree(build_dir, ignore_errors=True)


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
    
    if not all([container_name, image_name, container_port, host_port]):
        return jsonify({'error': 'missing required fields'}), 400
    
    try:
        # Remove existing container if any
        subprocess.run(['docker', 'rm', '-f', container_name], capture_output=True)
        
        cmd = [
            'docker', 'run', '-d',
            '--name', container_name,
            '-p', f'{host_port}:{container_port}',
            '-v', '/data:/app/data',
            '--restart', 'unless-stopped',
        ]
        
        for env in env_variables:
            cmd.extend(['-e', env])
        
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
    """Stop and remove a container."""
    container_name = request.args.get('container_name') or (request.json or {}).get('container_name')
    if not container_name:
        return jsonify({'error': 'container_name required'}), 400
    
    try:
        subprocess.run(['docker', 'stop', container_name], capture_output=True)
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
        return jsonify({
            'container_name': container_name,
            'state': parts[0] if parts else 'unknown',
            'health_status': parts[1] if len(parts) > 1 else 'none',
            'running': parts[2] == 'true' if len(parts) > 2 else False
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# HEALTH CHECK
# =============================================================================

def parse_logs_for_errors(container_name, max_errors=5):
    """Parse docker logs for errors."""
    try:
        result = subprocess.run(
            ['docker', 'logs', '--tail', '200', container_name],
            capture_output=True, text=True
        )
        
        logs = result.stdout + result.stderr
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
    """TCP ping to check if port is reachable."""
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
        
        for line in result.stdout.strip().split('\n'):
            if '->' in line:
                parts = line.split('->')
                if len(parts) == 2:
                    host_part = parts[1].strip()
                    if ':' in host_part:
                        return int(host_part.split(':')[-1])
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
    1. Parse logs for errors
    2. Check if running
    3. TCP ping
    4. Return status
    """
    container_name = request.args.get('container_name')
    if not container_name:
        return jsonify({'error': 'container_name required'}), 400
    
    errors = parse_logs_for_errors(container_name)
    container_info = get_container_info(container_name)
    
    if not container_info or container_info.get('status') != 'running':
        return jsonify({
            'status': 'unhealthy',
            'reason': 'not running',
            'details': errors,
            'container_info': container_info
        })
    
    host_port = get_container_host_port(container_name)
    
    if host_port and not tcp_ping('127.0.0.1', host_port, timeout=5):
        return jsonify({
            'status': 'unhealthy',
            'reason': 'running but timed out',
            'details': errors,
            'container_info': container_info
        })
    
    if errors:
        return jsonify({
            'status': 'degraded',
            'reason': 'running but errors in logs',
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

def get_private_ip() -> str:
    """Get the droplet's private/VPC IP address."""
    try:
        # DigitalOcean private IPs are typically on eth1 or in 10.x.x.x range
        result = subprocess.run(
            ['ip', '-4', 'addr', 'show'],
            capture_output=True, text=True
        )
        
        for line in result.stdout.split('\n'):
            if 'inet ' in line and '10.' in line:
                # Extract IP from "inet 10.x.x.x/xx" format
                match = re.search(r'inet (10\.\d+\.\d+\.\d+)', line)
                if match:
                    return match.group(1)
        
        return None
    except Exception:
        return None


if __name__ == '__main__':
    # Managed mode: bind to VPC IP only (more secure)
    # Customer mode: bind to all interfaces (required for external access)
    managed_mode = os.environ.get('MANAGED_MODE', 'false').lower() == 'true'
    
    if managed_mode:
        private_ip = get_private_ip()
        if private_ip:
            print(f"[Managed Mode] Binding to VPC IP: {private_ip}")
            app.run(host=private_ip, port=9999)
        else:
            print("[Managed Mode] Warning: No private IP found, falling back to 0.0.0.0")
            app.run(host='0.0.0.0', port=9999)
    else:
        print("[Customer Mode] Binding to all interfaces: 0.0.0.0")
        app.run(host='0.0.0.0', port=9999)


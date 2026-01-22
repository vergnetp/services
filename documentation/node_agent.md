\# Node Agent API Endpoints



Complete reference for all HTTP endpoints available on the node agent running on deployment droplets.



\## Base URL



```

http://<droplet-ip>:9999

```



\## Authentication



\### Security Layers (Applied in Order)



1\. \*\*IP Allowlist\*\* (Optional) - If `NODE\_AGENT\_ALLOWED\_IPS` is set, \*\*only those IPs\*\* can access any endpoint

2\. \*\*API Key Requirement\*\* (Default Enforced) - \*\*All endpoints require API key\*\* (`NODE\_AGENT\_REQUIRE\_AUTH\_ALWAYS=true` by default)

3\. \*\*Endpoint-Specific Auth\*\* - Critical endpoints explicitly enforce `@require\_api\_key` decorator



\### Public Endpoint (No Auth)

\- `GET /ping` - Health check for load balancers and monitoring systems



All other endpoints require:

\- \*\*Header\*\*: `X-API-Key: <hmac-sha256-signature>`

\- \*\*Computed as\*\*: `HMAC-SHA256(do\_token, "node-agent:")`

\- \*\*Key location\*\*: Generated fresh from DO token each deployment



\### Environment Variables

\- `NODE\_AGENT\_REQUIRE\_AUTH\_ALWAYS=true` (default) - \*\*Require API key for all requests\*\* (including from VPC)

\- `NODE\_AGENT\_ALLOWED\_IPS=10.120.0.5,192.168.1.1` (optional) - Whitelist specific IPs only

\- Both can be combined: IP check runs first, then API key validation



---



\## Health \& Monitoring



\### `GET /ping`

Simple alive check - returns Docker status and agent version.



\*\*Auth\*\*: Public  

\*\*Response\*\*:

```json

{

&nbsp; "status": "ok|degraded|error",

&nbsp; "version": "2.6.1",

&nbsp; "docker": true

}

```



\### `GET /metrics`

Get container and system metrics (CPU, memory, network, disk).



\*\*Auth\*\*: API Key  

\*\*Response\*\*: Container metrics object



---



\## Container Management



\### `GET /containers`

List all containers (running and stopped).



\*\*Auth\*\*: API Key  

\*\*Response\*\*:

```json

{

&nbsp; "containers": \[

&nbsp;   {

&nbsp;     "ID": "sha256:abc123...",

&nbsp;     "Names": "/myapp",

&nbsp;     "Image": "nginx:latest",

&nbsp;     "Status": "Up 2 hours",

&nbsp;     ...

&nbsp;   }

&nbsp; ]

}

```



\### `POST /containers/run`

Start a Docker container.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "name": "myapp",

&nbsp; "image": "nginx:latest",

&nbsp; "ports": \["80:80", "443:443"],

&nbsp; "environment": \["DEBUG=1", "NODE\_ENV=prod"],

&nbsp; "volumes": \["/local/data:/app/data"],

&nbsp; "network": "app-network",

&nbsp; "restart\_policy": "unless-stopped",

&nbsp; "health\_check": {

&nbsp;   "test": "curl http://localhost/ || exit 1",

&nbsp;   "interval": 30,

&nbsp;   "timeout": 10,

&nbsp;   "retries": 3

&nbsp; }

}

```



\*\*Response\*\*: Container creation result



\### `POST /containers/<n>/start`

Start a stopped container.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID



\### `POST /containers/<n>/stop`

Stop a running container.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID

\- `timeout` (query) = seconds before force-kill (default: 10)



\### `POST /containers/<n>/restart`

Restart a container.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID



\### `POST /containers/<n>/remove`

Remove a container.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID

\- `force` (query) = force remove (default: false)

\- `volumes` (query) = remove volumes (default: false)



\### `GET /containers/<n>/status`

Get container status.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID



\*\*Response\*\*:

```json

{

&nbsp; "id": "sha256:abc123...",

&nbsp; "name": "myapp",

&nbsp; "state": "running|exited|paused",

&nbsp; "status": "Up 2 hours",

&nbsp; "health\_status": "healthy|unhealthy|none"

}

```



\*\*Auth\*\*: API Key Required  

\*\*Params\*\*: 

\- `<n>` = container name or ID



\*\*Response\*\*: Health status with timestamp



\### `GET /containers/all/health`

Get health status for all containers.



\*\*Auth\*\*: API Key Required  

\*\*Response\*\*: Map of container names to health status



\### `GET /containers/<n>/logs`

Get container logs.



\*\*Auth\*\*: API Key Required  

\*\*Params\*\*:

\- `<n>` = container name or ID

\- `tail` (query) = number of lines (default: 100)

\- `follow` (query) = stream logs (default: false)



\*\*Response\*\*: Log output



\### `GET /containers/<n>/inspect`

Get full container inspection data (for recreating with same config).



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID



\*\*Response\*\*: Full Docker inspect JSON



\### `POST /containers/<n>/exec`

Execute command in running container.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = container name or ID



\*\*Body\*\*:

```json

{

&nbsp; "command": \["sh", "-c", "echo 'hello world'"],

&nbsp; "user": "root",

&nbsp; "workdir": "/app"

}

```



\*\*Response\*\*: Command output with exit code



---



\## Docker Images



\### `GET /images/list`

List Docker images, optionally filtered by prefix.



\*\*Auth\*\*: API Key  

\*\*Query Params\*\*:

\- `prefix` = filter images by name prefix (optional)



\*\*Response\*\*:

```json

{

&nbsp; "images": \[

&nbsp;   {

&nbsp;     "ID": "sha256:xyz789...",

&nbsp;     "RepoTags": \["nginx:latest", "nginx:1.21"],

&nbsp;     "Size": 142857,

&nbsp;     "Created": "2024-01-15T10:30:00Z"

&nbsp;   }

&nbsp; ]

}

```



\### `POST /images/pull`

Pull a Docker image, optionally with registry credentials.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "image": "nginx:latest",

&nbsp; "registry": "docker.io",  // optional

&nbsp; "username": "user",       // optional

&nbsp; "password": "pass"        // optional

}

```



\*\*Response\*\*: Pull result with image details



\### `POST /images/tag`

Tag an image for deployment history/rollback.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "source\_image": "myapp:latest",

&nbsp; "target\_image": "myapp:deploy\_4bd0ed9b"

}

```



\*\*Response\*\*: Tagging result



\### `POST /images/load`

Load Docker image from tar file (docker save output).



Accepts either:

\- `multipart/form-data` with `image\_tar` file (preferred, streams to disk)

\- `application/json` with `image\_tar\_b64` base64 encoded (legacy, high memory)



\*\*Auth\*\*: API Key  

\*\*Content-Type\*\*: `multipart/form-data` or `application/json`



\*\*Response\*\*: Load result



\### `POST /images/cleanup`

Cleanup unused Docker images.



\*\*Auth\*\*: API Key Required (⚠️ Destructive operation)  

\*\*Response\*\*: Cleanup result with number removed



---



\## Docker Operations



\### `POST /docker/build`

Build Docker image from uploaded code.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "context\_path": "/tmp/context",

&nbsp; "dockerfile": "Dockerfile",  // optional

&nbsp; "tag": "myapp:1.0",

&nbsp; "build\_args": {

&nbsp;   "NODE\_ENV": "production"

&nbsp; }

}

```



\*\*Response\*\*: Build result with image ID



\### `POST /docker/dockerfile`

Get or generate Dockerfile for preview/editing before build.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "context\_path": "/tmp/code",

&nbsp; "generate": true  // auto-generate if missing

}

```



\*\*Response\*\*: Dockerfile contents



\### `POST /docker/login`

Login to a Docker registry.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "registry": "gcr.io",

&nbsp; "username": "user",

&nbsp; "password": "pass"

}

```



\*\*Response\*\*: Login result



\### `POST /docker/load`

Load Docker image from tar file.



Accepts either:

\- `multipart/form-data` with `image\_tar` file

\- `application/json` with `image\_tar\_b64` base64-encoded data



\*\*Auth\*\*: API Key  

\*\*Response\*\*: Load result with image details



\### `POST /docker/load/stream`

Load Docker image from streamed tar data.



Accepts raw tar bytes in request body - enables true streaming from upstream without buffering entire file.



\*\*Auth\*\*: API Key  

\*\*Content-Type\*\*: `application/octet-stream` or `application/x-tar`  

\*\*Body\*\*: Raw tar file bytes



\*\*Response\*\*: Load result



---



\## File Operations



\### `POST /files/write`

Write file to allowed path.



\*\*Allowed paths\*\*:

\- `/local/`

\- `/app/`

\- `/etc/nginx/`

\- `/tmp/`



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "path": "/local/config.json",

&nbsp; "content": "file contents",

&nbsp; "mode": 644  // optional

}

```



\*\*Response\*\*: Write result



\### `GET /files/read`

Read file contents.



\*\*Auth\*\*: API Key  

\*\*Query Params\*\*:

\- `path` = file path



\*\*Response\*\*:

```json

{

&nbsp; "path": "/local/config.json",

&nbsp; "content": "file contents",

&nbsp; "size": 1024

}

```



\### `GET /files/exists`

Check if file exists.



\*\*Auth\*\*: API Key  

\*\*Query Params\*\*:

\- `path` = file path



\*\*Response\*\*:

```json

{

&nbsp; "exists": true,

&nbsp; "path": "/local/config.json",

&nbsp; "size": 1024,

&nbsp; "modified": "2024-01-15T10:30:00Z"

}

```



\### `POST /files/mkdir`

Create directory with parents.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "path": "/local/data/uploads",

&nbsp; "mode": 755  // optional

}

```



\*\*Response\*\*: Creation result



\### `POST /files/delete`

Delete a file.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "path": "/local/old-config.json"

}

```



\*\*Response\*\*: Deletion result



---



\## File Upload



\### `POST /upload/tar`

Upload and extract tar.gz archive.



Accepts either:

\- `multipart/form-data` with `tar\_file` file (preferred, streams to disk)

\- `application/json` with `data` base64-encoded (legacy, high memory)



\*\*Auth\*\*: API Key  

\*\*Query Params\*\*:

\- `extract\_path` = where to extract (required)



\*\*Response\*\*: Extraction result



\### `POST /upload/tar/stream`

Upload and extract tar.gz archive from streamed data.



Accepts raw tar.gz bytes in request body - enables true streaming from upstream without buffering.



\*\*Auth\*\*: API Key  

\*\*Content-Type\*\*: `application/octet-stream` or `application/gzip`  

\*\*Query Params\*\*:

\- `extract\_path` = where to extract (required)  

\*\*Body\*\*: Raw tar.gz bytes



\*\*Response\*\*: Extraction result



\### `POST /upload/tar/chunked`

Upload tar in chunks (resumable upload).



\*\*Auth\*\*: API Key  

\*\*Query Params\*\*:

\- `chunk\_id` = unique chunk identifier

\- `chunk\_index` = 0-based chunk number

\- `total\_chunks` = total number of chunks

\- `extract\_path` = where to extract (final chunk only)



\*\*Body\*\*: Raw chunk bytes



\*\*Response\*\*: Chunk acceptance result



---



\## Git Operations



\### `POST /git/clone`

Clone a git repository with optional credentials.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "url": "https://github.com/user/repo.git",

&nbsp; "target\_path": "/local/repo",

&nbsp; "branch": "main",  // optional

&nbsp; "username": "user",  // optional (for private repos)

&nbsp; "password": "token"  // optional

}

```



\*\*Response\*\*: Clone result



---



\## Networks



\### `POST /networks/create`

Create Docker network.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "name": "app-network",

&nbsp; "driver": "bridge",

&nbsp; "ipam\_config": {

&nbsp;   "subnet": "172.20.0.0/16",

&nbsp;   "gateway": "172.20.0.1"

&nbsp; }

}

```



\*\*Response\*\*: Network creation result



\### `GET /networks/<n>`

Get Docker network details.



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = network name or ID



\*\*Response\*\*: Network details (connected containers, config, etc.)



---



\## Nginx



\### `GET /nginx/test`

Test nginx configuration.



\*\*Auth\*\*: API Key  

\*\*Response\*\*: Test result (valid/invalid)



\### `POST /nginx/reload`

Reload nginx configuration (works with both Docker and systemctl).



\*\*Auth\*\*: API Key  

\*\*Response\*\*: Reload result



---



\## Scheduled Tasks (Cron)



\### `GET /cron/jobs`

List all managed cron jobs.



\*\*Auth\*\*: API Key  

\*\*Response\*\*:

```json

{

&nbsp; "jobs": \[

&nbsp;   {

&nbsp;     "id": "cron\_123abc",

&nbsp;     "schedule": "0 2 \* \* \*",

&nbsp;     "command": "docker run --rm myapp /cleanup.sh",

&nbsp;     "created": "2024-01-15T10:30:00Z"

&nbsp;   }

&nbsp; ]

}

```



\### `POST /cron/run-docker`

Schedule a Docker container to run on a schedule.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "schedule": "0 2 \* \* \*",  // cron format

&nbsp; "image": "myapp:latest",

&nbsp; "command": \["/bin/sh", "-c", "cleanup.sh"],

&nbsp; "environment": \["DEBUG=1"],

&nbsp; "volumes": \["/local/data:/data"],

&nbsp; "networks": \["app-network"]

}

```



\*\*Response\*\*: Job creation result with job ID



\### `POST /cron/remove`

Remove a cron job by ID.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "job\_id": "cron\_123abc"

}

```



\*\*Response\*\*: Removal result



---



\## Service Control



\### `GET /services/<n>/status`

Get service status (nginx, docker, node-agent).



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = service name (`nginx`, `docker`, `node-agent`)



\*\*Response\*\*:

```json

{

&nbsp; "service": "nginx",

&nbsp; "active": true,

&nbsp; "enabled": true,

&nbsp; "uptime": 3600

}

```



\### `POST /services/<n>/restart`

Restart a service (nginx, docker, node-agent).



\*\*Auth\*\*: API Key  

\*\*Params\*\*: 

\- `<n>` = service name



\*\*Response\*\*: Restart result



---



\## Firewall (UFW)



\### `GET /firewall/status`

Get UFW firewall status.



\*\*Auth\*\*: API Key  

\*\*Response\*\*:

```json

{

&nbsp; "status": "active|inactive",

&nbsp; "rules": \[

&nbsp;   {

&nbsp;     "action": "ALLOW",

&nbsp;     "port": 80,

&nbsp;     "protocol": "tcp",

&nbsp;     "from\_ip": "0.0.0.0/0"

&nbsp;   }

&nbsp; ]

}

```



\### `POST /firewall/allow`

Add UFW allow rule.



\*\*Auth\*\*: API Key  

\*\*Body\*\*:

```json

{

&nbsp; "port": 8080,

&nbsp; "protocol": "tcp",  // optional (default: both)

&nbsp; "from\_ip": "10.0.0.0/8"  // optional (default: anywhere)

}

```



\*\*Response\*\*: Rule creation result



---



\## Error Responses



All endpoints return errors in this format:



```json

{

&nbsp; "error": "Error message",

&nbsp; "details": "Additional details (if available)"

}

```



\*\*Common HTTP Status Codes\*\*:

\- `200` - Success

\- `201` - Created

\- `400` - Bad request (invalid parameters)

\- `401` - Unauthorized (missing/invalid API key)

\- `403` - Forbidden (IP not allowed, path not allowed, etc.)

\- `404` - Not found

\- `500` - Server error

\- `503` - Service unavailable



---



\## Security Summary



| Layer | Mechanism | Notes |

|-------|-----------|-------|

| 1 | IP Allowlist | `NODE\_AGENT\_ALLOWED\_IPS` env var (comma-separated) |

| 2 | VPC Bypass | Private IPs skip auth by default |

| 3 | API Key | `X-API-Key` header for public requests |

| 4 | Path Restrictions | File operations limited to `/local/`, `/app/`, `/etc/nginx/`, `/tmp/` |

| 5 | Service Whitelist | Only `nginx`, `docker`, `node-agent` can be controlled |



---



\## Version



Current agent version: `2.6.1`



Check version: `GET /ping`


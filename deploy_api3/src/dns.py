"""Cloudflare DNS management."""

from typing import List, Dict, Any
from shared_libs.backend.cloudflare import AsyncCFClient

async def setup_multi_server(cf_token: str, domain: str, ips: List[str]) -> Dict[str, Any]:
    """Create A records for all IPs (round-robin)."""    
    
    async with AsyncCFClient(api_token=cf_token) as client:
        existing = await client.get_dns_records(domain)
        for record in existing:
            if record.get('type') == 'A':
                await client.delete_dns_record(domain, record['id'])
        
        created = []
        for ip in ips:
            record = await client.create_dns_record(domain=domain, record_type='A', content=ip, proxied=True)
            created.append(record)
        
        return {'domain': domain, 'records': created}


async def remove_domain(cf_token: str, domain: str) -> Dict[str, Any]:
    """Delete all DNS records for domain."""
   
    async with AsyncCFClient(api_token=cf_token) as client:
        existing = await client.get_dns_records(domain)
        deleted = []
        for record in existing:
            await client.delete_dns_record(domain, record['id'])
            deleted.append(record['id'])
        return {'domain': domain, 'deleted': deleted}

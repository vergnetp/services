"""
Cloudflare DNS management.
"""

from typing import List, Dict, Any


async def setup_multi_server(cf_token: str, domain: str, ips: List[str]) -> Dict[str, Any]:
    """Create A records for all IPs (round-robin load balancing)."""
    from backend.cloudflare import AsyncCFClient
    
    async with AsyncCFClient(api_token=cf_token) as client:
        # Remove existing records
        existing = await client.get_dns_records(domain)
        for record in existing:
            if record.get('type') == 'A':
                await client.delete_dns_record(domain, record['id'])
        
        # Create new records
        created = []
        for ip in ips:
            record = await client.create_dns_record(
                domain=domain,
                record_type='A',
                content=ip,
                proxied=True,
            )
            created.append(record)
        
        return {'domain': domain, 'records': created}


async def remove_domain(cf_token: str, domain: str) -> Dict[str, Any]:
    """Delete all DNS records for domain."""
    from backend.cloudflare import AsyncCFClient
    
    async with AsyncCFClient(api_token=cf_token) as client:
        existing = await client.get_dns_records(domain)
        deleted = []
        
        for record in existing:
            await client.delete_dns_record(domain, record['id'])
            deleted.append(record['id'])
        
        return {'domain': domain, 'deleted': deleted}


async def get_domain_records(cf_token: str, domain: str) -> List[Dict[str, Any]]:
    """Get DNS records for domain."""
    from backend.cloudflare import AsyncCFClient
    
    async with AsyncCFClient(api_token=cf_token) as client:
        return await client.get_dns_records(domain)

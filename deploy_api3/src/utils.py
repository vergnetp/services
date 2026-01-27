"""
Utility functions.
"""


from typing import Dict, List
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_env_variables(env_list: List[str]) -> Dict[str, str]:
    """['KEY=value', ...] -> {'KEY': 'value', ...}"""
    result = {}
    for item in env_list or []:
        if '=' in item:
            key, value = item.split('=', 1)
            result[key] = value
    return result

def is_stateful(service_type: str) -> bool:
    """Everything that is not a webservice, worker or scheduled task is deemed stateful"""
    return service_type not in ('webservice','worker','schedule')


def is_webservice(service_type: str) -> bool:
    """Everything that is a webservice"""
    return service_type == 'webservice'


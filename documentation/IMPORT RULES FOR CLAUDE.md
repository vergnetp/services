\# Import Rules for shared\_libs/backend



\## ⚠️ CRITICAL: Always Use Relative Imports for Sibling Packages



\### The Problem



`shared\_libs/backend/` contains multiple sibling packages:



```

shared\_libs/backend/

├── ai/

├── app\_kernel/

├── cloud/

├── databases/

├── http\_client/

├── infra/

├── resilience/

├── streaming/

└── ...

```



\*\*NEVER\*\* use absolute imports between these packages:



```python

\# ❌ WRONG - Will fail if PYTHONPATH isn't set exactly right

from cloud.llm import AsyncAnthropicClient

from http\_client import get\_pooled\_client

from databases import DatabaseManager

```



\*\*ALWAYS\*\* use relative imports:



```python

\# ✅ CORRECT - Works regardless of how package is installed

from ..cloud.llm import AsyncAnthropicClient

from ..http\_client import get\_pooled\_client

from ..databases import DatabaseManager

```



---



\## How to Calculate the Relative Import Path



\### Step 1: Count Your Depth



Count how deep the importing file is within its package:



| File Location | Depth | Package Path |

|---------------|-------|--------------|

| `cloud/\_\_init\_\_.py` | 1 | `cloud` |

| `cloud/base.py` | 1 | `cloud` |

| `cloud/llm/\_\_init\_\_.py` | 2 | `cloud.llm` |

| `cloud/llm/base.py` | 2 | `cloud.llm` |

| `ai/ai\_agents/providers/anthropic.py` | 3 | `ai.ai\_agents.providers` |



\### Step 2: Calculate Dots Needed



To import a \*\*sibling package\*\* at the root level:

\- \*\*Dots needed = depth + 1\*\*



| From | Depth | Dots to Root | Example |

|------|-------|--------------|---------|

| `cloud/base.py` | 1 | `..` (2 dots) | `from ..http\_client import X` |

| `cloud/llm/base.py` | 2 | `...` (3 dots) | `from ...http\_client import X` |

| `ai/ai\_agents/providers/anthropic.py` | 3 | `....` (4 dots) | `from ....cloud.llm import X` |



\### Step 3: Add the Package Path



After the dots, add the target package path:



```python

\# From cloud/base.py (depth 1) to http\_client

from ..http\_client import get\_pooled\_client



\# From cloud/llm/base.py (depth 2) to http\_client  

from ...http\_client import get\_pooled\_client



\# From ai/ai\_agents/providers/anthropic.py (depth 3) to cloud.llm

from ....cloud.llm import AsyncAnthropicClient

```



---



\## Quick Reference Table



| From Package | To Package | Import Statement |

|--------------|------------|------------------|

| `cloud/\*` | `http\_client` | `from ..http\_client import X` |

| `cloud/llm/\*` | `http\_client` | `from ...http\_client import X` |

| `ai/ai\_agents/providers/\*` | `cloud.llm` | `from ....cloud.llm import X` |

| `infra/\*` | `cloud` | `from ..cloud import X` |

| `infra/deploy/\*` | `cloud` | `from ...cloud import X` |

| `app\_kernel/\*` | `databases` | `from ..databases import X` |

| `app\_kernel/auth/\*` | `databases` | `from ...databases import X` |



---



\## Within-Package Imports



For imports \*\*within the same top-level package\*\*, use single-dot relative imports:



```python

\# In cloud/digitalocean.py importing from cloud/base.py

from .base import CloudClientConfig  # ✅



\# In cloud/llm/anthropic.py importing from cloud/llm/base.py

from .base import AsyncLLMClient  # ✅



\# In cloud/llm/anthropic.py importing from cloud/llm/errors.py

from .errors import LLMError  # ✅



\# In cloud/llm/\_\_init\_\_.py importing from cloud/llm/anthropic.py

from .anthropic import AsyncAnthropicClient  # ✅

```



---



\## Lazy Imports (When Needed)



If you need to avoid circular imports or load modules lazily, put the import inside a function:



```python

def \_get\_client():

&nbsp;   """Import lazily to avoid circular imports."""

&nbsp;   from ....cloud.llm import AsyncAnthropicClient  # Still use relative!

&nbsp;   return AsyncAnthropicClient

```



---



\## Docstrings and Comments



Docstrings showing \*\*user-facing examples\*\* can use absolute imports (since users will have `PYTHONPATH` set):



```python

"""

Example usage (for users):

&nbsp;   

&nbsp;   from cloud.llm import AsyncAnthropicClient

&nbsp;   

&nbsp;   client = AsyncAnthropicClient(api\_key="...")

"""



\# But the actual code import must be relative:

from ..http\_client import get\_pooled\_client  # ✅

```



---



\## Verification Checklist



Before submitting code, run this check:



```bash

\# Find bad absolute imports in a package

grep -rn "^from cloud\\b\\|^from http\_client\\b\\|^from databases\\b\\|^from infra\\b\\|^from ai\\b\\|^from app\_kernel\\b" \\

&nbsp;   your\_package/ --include="\*.py" | grep -v \_\_pycache\_\_

```



If any matches show up that are NOT in docstrings/comments, they need to be fixed!



---



\## Summary



1\. \*\*Count your depth\*\* from the package root

2\. \*\*Add 1 to get the dots needed\*\* to reach sibling packages

3\. \*\*Append the target package path\*\*

4\. \*\*Test\*\* by grepping for absolute imports



```

Depth 1 (package/file.py):      from ..sibling import X

Depth 2 (package/sub/file.py):  from ...sibling import X  

Depth 3 (package/a/b/file.py):  from ....sibling import X

Depth 4 (package/a/b/c/file.py): from .....sibling import X

```


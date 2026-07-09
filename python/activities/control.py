"""Bridge so call_llm can read its OWN conversation's LLM kill-switch.

The worker stashes its Temporal client here at startup; call_llm queries the
workflow it's running under (`activity.info().workflow_id`) each attempt — so
the switch is scoped to that one conversation, not global. Resilient: any
failure → 'not down', so the switch can never itself break the LLM.
"""

from temporalio import activity
from temporalio.client import Client

_client: Client | None = None


def set_client(client: Client) -> None:
    global _client
    _client = client


async def llm_down() -> bool:
    if _client is None:
        return False
    try:
        wid = activity.info().workflow_id  # the conversation that called
        return bool(await _client.get_workflow_handle(wid).query("is_llm_down"))
    except Exception:
        return False

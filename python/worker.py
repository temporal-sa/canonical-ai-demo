"""Worker entrypoint (slide 34): polls the task queue, runs workflow + activities.

    uv run worker.py

Kill it mid-conversation and restart it — the loop resumes exactly where it
was. That's the crash-recovery demo beat.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

import config
from activities import control
from activities.llm import call_llm
from activities.tools import execute_tool
from workflows.agent import SupportAgentWorkflow


async def main() -> None:
    client = await config.temporal_client()
    control.set_client(client)  # so call_llm can read its conversation's kill-switch
    with ThreadPoolExecutor(max_workers=8) as activity_executor:
        worker = Worker(
            client,
            task_queue=config.TASK_QUEUE,
            workflows=[SupportAgentWorkflow],
            activities=[call_llm, execute_tool],
            activity_executor=activity_executor,
        )
        print(f"worker polling task queue '{config.TASK_QUEUE}' "
              f"on {config.TEMPORAL_ADDRESS} (provider: {config.LLM_PROVIDER})")
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

"""A fake Ollama for the real-model experiment's tests: right with a set chance."""

import json
import random
from collections.abc import Callable

import httpx

from research.stats_real.tasks import Task


def fake_ollama(
    tasks: list[Task], chance: Callable[[str, Task], float]
) -> Callable[[httpx.Request], httpx.Response]:
    """Answers each request right with chance(model, task), the same way every time."""
    by_prompt = {task.prompt: task for task in tasks}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        task = by_prompt[body["messages"][-1]["content"]]
        rng = random.Random(f"{body['model']}-{body.get('seed')}-{task.id}")
        right = rng.random() < chance(body["model"], task)
        text = task.answer if right else "I am not sure"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 3},
            },
        )

    return handler

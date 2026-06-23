"""
Generic Celery tasks for the AI harness.

Every public task here returns its result dict which is stored in Redis as the
Celery result backend, making it queryable via ``/<task_id>/status``.
"""

import traceback
from typing import Any

from infra.core.celery_app import celery
from infra.core.llm import chat_completion_sync

TASK_LOGS: dict[str, list[str]] = {}


def _log(task_id: str, msg: str):
    TASK_LOGS.setdefault(task_id, []).append(msg)


# ---------------------------------------------------------------------------
# Core tasks
# ---------------------------------------------------------------------------


@celery.task(
    bind=True,
    name="tasks.run_prompt",
    track_started=True,
)
def run_prompt(
    self,
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a single LLM prompt asynchronously.

    Parameters
    ----------
    prompt:
        User message to send to the LLM.
    model:
        Model identifier — forwarded to LiteLLM.  Defaults to the harness
        default (``HARNESS_MODEL`` env var).
    system:
        Optional system prompt.
    max_tokens:
        Optional upper bound on response length.

    Returns
    -------
    dict with ``result`` (str), ``model`` (str), and ``error`` (str | None).
    """
    task_id = self.request.id
    _log(task_id, f"starting prompt task — model={model or 'default'}")

    try:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = chat_completion_sync(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
        )

        _log(task_id, "completed successfully")

        return {
            "result": response,
            "model": model or "default",
            "error": None,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        _log(task_id, f"failed: {exc}")

        return {
            "result": None,
            "model": model or "default",
            "error": f"{exc}\n{tb}",
        }


@celery.task(
    bind=True,
    name="tasks.run_llm_chain",
    track_started=True,
)
def run_llm_chain(
    self,
    steps: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Run a sequential chain of LLM prompts.

    Each step is a dict with ``prompt`` and optional ``system``.
    The output of one step is injected into the next step's prompt via
    the ``{{previous}}`` placeholder.

    Returns
    -------
    dict with ``results`` (list of str), ``model``, and ``error``.
    """
    task_id = self.request.id
    _log(task_id, f"starting chain with {len(steps)} steps")

    previous_output: str | None = None

    results: list[str] = []

    try:
        for idx, step in enumerate(steps):
            prompt = step.get("prompt", "")
            system = step.get("system")

            if previous_output is not None:
                prompt = prompt.replace("{{previous}}", previous_output)

            messages: list[dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            response = chat_completion_sync(
                messages=messages,
                model=model,
            )

            previous_output = response
            results.append(response)
            _log(task_id, f"step {idx + 1}/{len(steps)} completed")

        _log(task_id, "chain completed successfully")

        return {
            "results": results,
            "model": model or "default",
            "error": None,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        _log(task_id, f"chain failed: {exc}")

        return {
            "results": results,
            "model": model or "default",
            "error": f"{exc}\n{tb}",
        }


@celery.task(
    bind=True,
    name="tasks.python_executor",
    track_started=True,
)
def python_executor(
    self,
    code: str,
    globals_dict: dict[str, Any] | None = None,
    locals_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute arbitrary Python code and return the result.

    Warning: this runs code inside the *worker* process.  Only use with
    trusted input.

    Parameters
    ----------
    code:
        Python source to ``exec``.
    globals_dict / locals_dict:
        Optional namespaces injected into the ``exec`` call.

    Returns
    -------
    dict with ``result`` (str — stdout captured), ``return_value`` (any JSON-
    serialisable object set via ``result_var`` in locals), and ``error``.
    """
    task_id = self.request.id
    _log(task_id, "starting python executor")

    try:
        # Capture stdout via a special locals key
        namespace: dict[str, Any] = {"__builtins__": __builtins__}
        if globals_dict:
            namespace.update(globals_dict)
        if locals_dict:
            namespace.update(locals_dict)

        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            exec(code, namespace, namespace)  # noqa: S102
        finally:
            sys.stdout = old_stdout

        return_value = namespace.get("result_var")

        return {
            "result": captured.getvalue(),
            "return_value": return_value,
            "error": None,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        return {
            "result": None,
            "return_value": None,
            "error": f"{exc}\n{tb}",
        }

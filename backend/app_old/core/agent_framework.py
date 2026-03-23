"""
Agentic LLM orchestration framework.

Optimized for sequential local-LLM queries with a clear path to parallel execution.
Each analysis dimension is an AgentTask; the executor runs them and emits granular
progress events per task.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from langchain_ollama import ChatOllama

from app import settings
from app.core.ollama_config import get_ollama_num_gpu

_log = logging.getLogger("uvicorn.error")

ProgressCallback = Callable[[str, dict[str, Any]], None]
CancelCheck = Callable[[], bool]


class TaskCancelled(Exception):
    pass


class TaskFailed(Exception):
    def __init__(self, task_name: str, detail: str):
        self.task_name = task_name
        super().__init__(f"Task '{task_name}' failed: {detail}")


@dataclass
class AgentTask:
    """A single unit of LLM work in the pipeline."""
    name: str
    prompt_builder: Callable[..., str]
    model_key: str = "fast"
    num_predict: int = 1200
    temperature: float = 0.3
    num_ctx: int = 2048
    max_retries: int = 2
    validator: Optional[Callable[[str], bool]] = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_name: str
    output: str
    elapsed_ms: int
    retries_used: int
    success: bool
    error: Optional[str] = None


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _get_model_name(model_key: str) -> str:
    if model_key == "fast":
        return _resolve_fast_model()
    return settings.LLM_MODEL


_fast_model_cache: tuple[float, str] | None = None
_FAST_MODEL_CACHE_TTL = 60.0


def _resolve_fast_model() -> str:
    import subprocess
    global _fast_model_cache
    now = time.monotonic()
    if _fast_model_cache and (now - _fast_model_cache[0]) < _FAST_MODEL_CACHE_TTL:
        return _fast_model_cache[1]
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if settings.FAST_LLM_MODEL.split(":")[0] in result.stdout:
            _fast_model_cache = (now, settings.FAST_LLM_MODEL)
            return settings.FAST_LLM_MODEL
    except Exception:
        pass
    _fast_model_cache = (now, settings.LLM_MODEL)
    return settings.LLM_MODEL


def _invoke_llm(task: AgentTask, prompt: str) -> str:
    model = _get_model_name(task.model_key)
    llm = ChatOllama(
        model=model,
        num_predict=task.num_predict,
        temperature=task.temperature,
        num_ctx=task.num_ctx,
        num_gpu=get_ollama_num_gpu(),
    )
    response = llm.invoke(prompt)
    return _strip_thinking(response.content)


class SequentialExecutor:
    """Runs AgentTasks one by one, emitting progress per task."""

    def __init__(
        self,
        tasks: list[AgentTask],
        progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ):
        self.tasks = tasks
        self.progress = progress
        self.should_cancel = should_cancel
        self.results: dict[str, TaskResult] = {}

    def _emit(self, phase: str, data: dict[str, Any] | None = None) -> None:
        if self.progress:
            self.progress(phase, data or {})

    def _check_cancel(self) -> None:
        if self.should_cancel and self.should_cancel():
            raise TaskCancelled()

    def run(self, prompt_context: dict[str, Any]) -> dict[str, TaskResult]:
        for task in self.tasks:
            self._check_cancel()
            model_name = _get_model_name(task.model_key)
            self._emit("task_start", {
                "task": task.name,
                "model": model_name,
            })

            t0 = time.monotonic()
            last_error: str | None = None

            for attempt in range(task.max_retries + 1):
                try:
                    dep_outputs = {
                        name: self.results[name].output
                        for name in task.depends_on
                        if name in self.results and self.results[name].success
                    }
                    prompt = task.prompt_builder(context=prompt_context, prior_results=dep_outputs)
                    raw = _invoke_llm(task, prompt)

                    if task.validator and not task.validator(raw):
                        if attempt < task.max_retries:
                            last_error = "Output validation failed, retrying with stricter prompt"
                            self._emit("task_retry", {
                                "task": task.name,
                                "attempt": attempt + 1,
                                "reason": "validation_failed",
                            })
                            continue
                        raw = raw or "(No valid output after retries)"

                    elapsed = int((time.monotonic() - t0) * 1000)
                    self.results[task.name] = TaskResult(
                        task_name=task.name,
                        output=raw,
                        elapsed_ms=elapsed,
                        retries_used=attempt,
                        success=True,
                    )
                    self._emit("task_done", {
                        "task": task.name,
                        "elapsed_ms": elapsed,
                        "retries": attempt,
                    })
                    break

                except TaskCancelled:
                    raise
                except Exception as e:
                    last_error = str(e)
                    if attempt < task.max_retries:
                        self._emit("task_retry", {
                            "task": task.name,
                            "attempt": attempt + 1,
                            "reason": str(e)[:200],
                        })
                        time.sleep(min(2 ** attempt, 8))
                        continue

                    elapsed = int((time.monotonic() - t0) * 1000)
                    self.results[task.name] = TaskResult(
                        task_name=task.name,
                        output="",
                        elapsed_ms=elapsed,
                        retries_used=attempt,
                        success=False,
                        error=last_error,
                    )
                    self._emit("task_error", {
                        "task": task.name,
                        "elapsed_ms": elapsed,
                        "error": last_error[:300] if last_error else "unknown",
                    })
                    raise TaskFailed(task.name, last_error or "unknown")

        return self.results


class ParallelExecutor:
    """
    Runs independent AgentTasks concurrently via thread pool.
    Tasks with dependencies still wait for their deps to complete.
    Enabled via ENABLE_PARALLEL_AGENTS setting.
    """

    def __init__(
        self,
        tasks: list[AgentTask],
        progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
        max_workers: int = 3,
    ):
        self.tasks = tasks
        self.progress = progress
        self.should_cancel = should_cancel
        self.max_workers = max_workers
        self.results: dict[str, TaskResult] = {}

    def _emit(self, phase: str, data: dict[str, Any] | None = None) -> None:
        if self.progress:
            self.progress(phase, data or {})

    def run(self, prompt_context: dict[str, Any]) -> dict[str, TaskResult]:
        independent = [t for t in self.tasks if not t.depends_on]
        dependent = [t for t in self.tasks if t.depends_on]

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for task in independent:
                futures[pool.submit(self._run_single, task, prompt_context, {})] = task

            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                    self.results[task.name] = result
                except Exception as e:
                    self.results[task.name] = TaskResult(
                        task_name=task.name, output="", elapsed_ms=0,
                        retries_used=0, success=False, error=str(e),
                    )

        for task in dependent:
            if self.should_cancel and self.should_cancel():
                raise TaskCancelled()
            dep_outputs = {
                name: self.results[name].output
                for name in task.depends_on
                if name in self.results and self.results[name].success
            }
            result = self._run_single(task, prompt_context, dep_outputs)
            self.results[task.name] = result

        return self.results

    def _run_single(self, task: AgentTask, context: dict, prior: dict) -> TaskResult:
        model_name = _get_model_name(task.model_key)
        self._emit("task_start", {"task": task.name, "model": model_name})
        t0 = time.monotonic()

        for attempt in range(task.max_retries + 1):
            try:
                prompt = task.prompt_builder(context=context, prior_results=prior)
                raw = _invoke_llm(task, prompt)
                if task.validator and not task.validator(raw):
                    if attempt < task.max_retries:
                        continue
                elapsed = int((time.monotonic() - t0) * 1000)
                result = TaskResult(task.name, raw, elapsed, attempt, True)
                self._emit("task_done", {"task": task.name, "elapsed_ms": elapsed})
                return result
            except Exception as e:
                if attempt == task.max_retries:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    self._emit("task_error", {"task": task.name, "error": str(e)[:300]})
                    raise TaskFailed(task.name, str(e)) from e
                time.sleep(min(2 ** attempt, 8))

        elapsed = int((time.monotonic() - t0) * 1000)
        return TaskResult(task.name, "", elapsed, task.max_retries, False, "exhausted retries")

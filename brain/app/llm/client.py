import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
from app.config import settings

log = logging.getLogger("brain.llm")


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: List[Dict[str, Any]] = []
    usage: LLMUsage = LLMUsage()
    latency_ms: float = 0.0
    model: str = ""


class LLMClient:
    """
    Configurable LLM client wrapper designed for seamless model & provider switching.
    Supports OpenAI, Anthropic, and compatible proxies.
    """

    def __init__(self):
        self._openai_client = None
        self._client_key: Optional[Tuple[str, str]] = None

    def _get_openai_client(self):
        settings.refresh_from_env()
        api_key = settings.OPENAI_API_KEY or settings.CODECRAFT_KEY or ""
        base_url = settings.OPENAI_BASE_URL or ""
        key_pair = (api_key, base_url)
        if self._openai_client is None or key_pair != self._client_key:
            import openai
            self._openai_client = openai.OpenAI(
                api_key=api_key or "sk-dummy",
                base_url=base_url or None,
                max_retries=1,
                timeout=25.0,
            )
            self._client_key = key_pair
        return self._openai_client

    def _execute_completion(
        self,
        chosen_model: str,
        formatted_messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]],
        retries: int,
        tool_choice: str,
    ) -> LLMResponse:
        start_time = time.perf_counter()
        last_error = None
        for attempt in range(retries + 1):
            try:
                client = self._get_openai_client()
                kwargs: Dict[str, Any] = {
                    "model": chosen_model,
                    "messages": formatted_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice if tool_choice in ("auto", "required", "none") else "auto"

                resp = client.chat.completions.create(**kwargs)
                latency = (time.perf_counter() - start_time) * 1000

                choice = resp.choices[0]
                text_content = choice.message.content or ""
                extracted_tool_calls = []

                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        extracted_tool_calls.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        })

                usage = LLMUsage()
                if resp.usage:
                    usage = LLMUsage(
                        prompt_tokens=resp.usage.prompt_tokens,
                        completion_tokens=resp.usage.completion_tokens,
                        total_tokens=resp.usage.total_tokens
                    )

                log.info(
                    "LLM complete model=%s latency_ms=%.1f tokens=%d",
                    chosen_model,
                    latency,
                    usage.total_tokens
                )

                return LLMResponse(
                    text=text_content,
                    tool_calls=extracted_tool_calls,
                    usage=usage,
                    latency_ms=round(latency, 2),
                    model=chosen_model
                )
            except Exception as e:
                last_error = e
                log.warning("LLM complete attempt %d failed: %s", attempt + 1, e)
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))

        log.error("LLM complete failed after %d attempts: %s", retries + 1, last_error)
        raise RuntimeError(f"LLM call failed: {last_error}") from last_error

    def complete(
        self,
        system: str,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 800,
        temperature: float = 0.2,
        tools: Optional[List[Dict[str, Any]]] = None,
        retries: int = 0,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """
        Executes a completion with automated retries, latency timing, and token accounting.
        Automatically falls back to settings.SUBAGENT_MODEL if the primary model fails.
        """
        settings.refresh_from_env()
        chosen_model = model or settings.SUBAGENT_MODEL

        api_key = settings.OPENAI_API_KEY or settings.CODECRAFT_KEY
        if not api_key:
            raise RuntimeError("No LLM API key configured in environment.")

        formatted_messages = []
        if system:
            formatted_messages.append({"role": "system", "content": system})
        formatted_messages.extend(messages)

        try:
            return self._execute_completion(
                chosen_model=chosen_model,
                formatted_messages=formatted_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=tools,
                retries=retries,
                tool_choice=tool_choice,
            )
        except Exception as primary_err:
            fallback_model = settings.SUBAGENT_MODEL
            err_lower = str(primary_err).lower()
            if (
                fallback_model
                and chosen_model != fallback_model
                and "connection error" not in err_lower
            ):
                log.warning(
                    "Primary model %s failed (%s); falling back to %s.",
                    chosen_model,
                    primary_err,
                    fallback_model,
                )
                return self._execute_completion(
                    chosen_model=fallback_model,
                    formatted_messages=formatted_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=tools,
                    retries=retries,
                    tool_choice=tool_choice,
                )
            raise

    def embed(self, text: str, model: Optional[str] = None) -> List[float]:
        """
        Generates text embedding vector.
        """
        chosen_model = model or settings.EMBEDDING_MODEL
        client = self._get_openai_client()
        resp = client.embeddings.create(input=[text], model=chosen_model)
        return resp.data[0].embedding


llm_client = LLMClient()

import time
from dataclasses import dataclass, field

from openai import OpenAI

from findocs import config

_client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> dict:
        message = {"role": "assistant", "content": self.text}
        if self.tool_calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return message


def chat(messages: list[dict], *, json_mode: bool = False, tools: list[dict] | None = None,
         model: str | None = None) -> LLMResult:
    extra = {}
    if json_mode:
        extra["response_format"] = {"type": "json_object"}
    if tools:
        extra["tools"] = tools
    started = time.monotonic()
    response = _client.chat.completions.create(
        model=model or config.DEEPSEEK_MODEL,
        messages=messages,
        temperature=0,
        extra_body={"thinking": {"type": "disabled"}},
        **extra,
    )
    message, usage = response.choices[0].message, response.usage
    return LLMResult(
        text=message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        seconds=time.monotonic() - started,
        tool_calls=[ToolCall(c.id, c.function.name, c.function.arguments) for c in message.tool_calls or []],
    )

"""Smoke-test script for LLM provider chain (requires real API keys).

Usage:
    python test_llm.py

This script prints the current chain and tries each model.
It is NOT a unittest — it's a manual-connected test.
"""

import sys

# Ensure we import from the project even when run directly
sys.path.insert(0, "")


def _safe_test(client, label: str, provider: str, model: str, **kwargs) -> bool:
    print(f"  Testing {label} ({provider} / {model}) ... ", end="", flush=True)
    try:
        result = client.chat(
            [{"role": "user", "content": "Say hi in one short sentence."}],
            **kwargs,
        )
        preview = (result.content or "<empty>").replace("\n", " ")[:100]
        print(f"OK → {preview}")
        return True
    except Exception as exc:
        print(f"FAILED reason={exc}")
        return False


def main() -> None:
    from src.services.llm_client import _build_chain, get_llm_client
    from src.services.llm_types import LLMModelSpec

    client = get_llm_client()
    chain: list[LLMModelSpec] = client._chain

    print("Current LLM chain:")
    for i, spec in enumerate(chain, 1):
        tool_tag = "tools" if spec.supports_tools else "no-tools"
        print(f"  {i}. {spec.provider} / {spec.model}  [{tool_tag}]")

    print()

    # Test unified client (should hit the first available model)
    print("Testing unified fallback client ... ", end="", flush=True)
    try:
        result = client.chat(
            [{"role": "user", "content": "Say hi in one short sentence."}]
        )
        preview = (result.content or "<empty>").replace("\n", " ")[:100]
        print(f"OK → {preview}")
    except Exception as exc:
        print(f"FAILED reason={exc}")

    print()

    # Test with tools (should skip models that don't support tools)
    print("Testing unified fallback client (with tools) ... ", end="", flush=True)
    try:
        result = client.chat(
            [{"role": "user", "content": "What is 2+2?"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "description": "Do math",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expression": {"type": "string"}
                            },
                            "required": ["expression"],
                        },
                    },
                }
            ],
        )
        preview = (result.content or "<empty>").replace("\n", " ")[:100]
        print(f"OK → {preview}")
    except Exception as exc:
        print(f"FAILED reason={exc}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()

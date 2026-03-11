"""LLM-as-judge using the OpenAI chat completions API.

The judge is given the rubric (a markdown prompt), the input, the candidate
output, and the checks, then asked to return a strict JSON verdict.

Why LLM judge instead of just local checks?
  Local checks are fast but can only validate structure.  An LLM judge can
  assess meaning, accuracy, and compliance with open-ended instructions.
"""

import json
import os

from openai import OpenAI


def llm_judge(
    case: dict,
    rubric_text: str,
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0,
    max_tokens: int = 300,
) -> dict:
    """Call the OpenAI chat API to score a single eval case.

    Args:
        case:         One record from the dataset JSONL file.
        rubric_text:  Full contents of the judge rubric markdown file.
        model:        OpenAI model to use (from config).
        temperature:  0 for deterministic scoring.
        max_tokens:   Token budget for the judge's response.

    Returns:
        { pass, score, reasons, parsed_json }  — same schema as local_judge.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. "
            "Set it in your environment or use runner.mode: mock in the config."
        )

    client = OpenAI(api_key=api_key)

    # Build the user prompt: rubric + case fields
    user_prompt = (
        f"{rubric_text}\n\n"
        f"---\n"
        f"input: {json.dumps(case['input'])}\n"
        f"candidate: {json.dumps(case['candidate'])}\n"
        f"checks: {json.dumps(case.get('checks', {}))}\n"
    )

    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.choices[0].message.content
    verdict = json.loads(raw)

    return {
        "pass": bool(verdict.get("pass", False)),
        "score": int(verdict.get("score", 0)),
        "reasons": verdict.get("reasons", []),
        "parsed_json": verdict.get("parsed_json"),
    }

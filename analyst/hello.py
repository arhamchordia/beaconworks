"""First OpenAI API call for the BeaconWorks analyst.

Reads the API key from the environment (or analyst/.env), sends one
request to the Responses API, and prints the answer plus usage.
Run: python3 analyst/hello.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI

MODEL = os.environ.get("BW_MODEL", "gpt-6-luna")


def main() -> int:
    # Values already set in the shell win over the .env file.
    load_dotenv(Path(__file__).parent / ".env")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        print("OPENAI_API_KEY is not set. Copy analyst/.env.example to analyst/.env and paste your key there.")
        return 1
    print(f"Using key ending in ...{key[-4:]} with model {MODEL}")

    client = OpenAI()
    try:
        response = client.responses.create(
            model=MODEL,
            input="In one sentence: what does a support ticket priority score help a team do?",
        )
    except AuthenticationError as error:
        print(f"The API rejected the key: {error.code}")
        if error.code == "expired_secret_key":
            print("This key has expired. Create a new key and update analyst/.env.")
        return 1

    print(response.output_text)
    print(f"model={response.model} input_tokens={response.usage.input_tokens} output_tokens={response.usage.output_tokens}")
    print(f"response id: {response.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

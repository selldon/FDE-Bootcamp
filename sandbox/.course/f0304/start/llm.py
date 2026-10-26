"""Talk to Claude: one function for every call."""
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()
MODEL = "claude-sonnet-5-5"


def ask(prompt):
    """Send one prompt and return the text of the reply."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[-1].text

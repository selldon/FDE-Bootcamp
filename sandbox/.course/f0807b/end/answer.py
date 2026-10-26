"""Answer a customer only from the chunks our search found, with their links."""
import sys
from datetime import date

from anthropic import transform_schema
from pydantic import BaseModel

from llm import ask
from prices import price
from search import search


class Reply(BaseModel):
    text: str
    pieces: list[int]


def answer(question, session):
    """The reply to the customer, and the links of the pieces it used."""
    found = search(question, session["market"], date.today())
    pieces = ""
    number = 0
    for title, section, body, url in found:
        number += 1
        if section == "Description":
            now = price(title, session)
            body += f" Price right now: {now['price']} {now['currency']}."
        pieces += f"Piece {number}, {title}, {section}:\n{body}\n\n"
    prompt = f"""You answer a DemoStore customer in two or three short sentences.
Use only the pieces of DemoStore's policies and products below.
If they do not answer the question, say you are not sure and offer a person.
List the numbers of the pieces you used.

{pieces}Question: {question}"""
    reply = ask(prompt, transform_schema(Reply))
    links = []
    for number in reply["pieces"]:
        url = found[number - 1][3]
        if url and url not in links:
            links.append(url)
    return reply["text"], links


if __name__ == "__main__":
    session = {"market": sys.argv[1], "company": None, "roles": []}
    text, links = answer(sys.argv[2], session)
    print(text)
    for link in links:
        print("Source:", link)

import typer
from pathlib import Path
from typing import Annotated, Optional
from rich.console import Console
from rich.markdown import Markdown
from vecstash.chunking import chunk_document

from vecstash.extraction import extract_files

from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter

app = typer.Typer(no_args_is_help=True, pretty_exceptions_short=True)
models_app = typer.Typer(no_args_is_help=True, help="Inspect and manage embedding models.")
app.add_typer(models_app, name="models")

console = Console(stderr=True)

@app.command()
def ingest(
    inputs: Annotated[list[Path], typer.Argument(help="Files to ingest (.txt, .md, .html, .pdf).")],
    json: Annotated[bool, typer.Option("--json", help="Emit as JSON.")] = False,
):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50
    )

    docs = extract_files(inputs)

    for doc in docs:
        chunks = chunk_document(doc)
        chunks_example = splitter.split_text(doc.text)
        console.print(chunks_example)
        console.print(chunks)

def main():
    app()
"""Render Mermaid diagram source files into SVG or PNG images."""

# ruff:file-ignore[implicit-namespace-package]

import argparse
import json
import os
import zlib
from base64 import urlsafe_b64encode
from collections.abc import Sequence
from pathlib import Path

import httpx
from mermaid import MermaidError
from rich.console import Console

ROOT_FOLDER = Path(__file__).resolve().parent.parent
DIAGRAMS_FOLDER = ROOT_FOLDER / 'diagrams'
_SUPPORTED_SUFFIXES = frozenset({'.mmd', '.mermaid'})
DEFAULT_RENDER_WIDTH = 2400
DEFAULT_RENDER_SCALE = 2.0
MERMAID_INK_TIMEOUT_SECONDS = 60.0
console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Render Mermaid diagrams from the diagrams directory.'
    )
    parser.add_argument(
        'sources',
        nargs='*',
        type=Path,
        help='Diagram files or directories. Defaults to diagrams/.',
    )
    parser.add_argument(
        '--format',
        dest='output_format',
        choices=('svg', 'png', 'both'),
        default='png',
        help='Output format. Defaults to png.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        help='Directory for rendered files. Defaults beside each source file.',
    )
    parser.add_argument(
        '--width',
        type=int,
        default=DEFAULT_RENDER_WIDTH,
        help=f'Render width in pixels. Defaults to {DEFAULT_RENDER_WIDTH}.',
    )
    parser.add_argument(
        '--scale',
        type=float,
        default=DEFAULT_RENDER_SCALE,
        help=f'Render scale from 1 to 3. Defaults to {DEFAULT_RENDER_SCALE}.',
    )
    return parser


def _collect_sources(sources: Sequence[Path]) -> list[Path]:
    roots = sources or (DIAGRAMS_FOLDER,)
    files: set[Path] = set()
    for root in roots:
        if root.is_dir():
            files.update(
                path
                for path in root.rglob('*')
                if path.is_file() and path.suffix in _SUPPORTED_SUFFIXES
            )
        elif root.is_file() and root.suffix in _SUPPORTED_SUFFIXES:
            files.add(root)
    return sorted(files)


def _formats(output_format: str) -> tuple[str, ...]:
    if output_format == 'both':
        return ('svg', 'png')
    return (output_format,)


def _encode_compressed_payload(source: str) -> str:
    """Encode Mermaid source using Mermaid Ink's compressed URL format.

    Parameters
    ----------
    source : str
        Mermaid source code.

    Returns
    -------
    str
        URL-safe ``pako:`` payload accepted by Mermaid Ink.
    """
    payload = json.dumps(
        {'code': source},
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    compressed = zlib.compress(payload, level=9)
    encoded = urlsafe_b64encode(compressed).decode('ascii').rstrip('=')
    return f'pako:{encoded}'


def _render_with_compressed_api(
    source_text: str,
    destination: Path,
    source_stem: str,
    formats: tuple[str, ...],
    width: int,
    scale: float,
) -> None:
    """Render a diagram through Mermaid Ink without an oversized request URI.

    Parameters
    ----------
    source_text : str
        Mermaid source code.
    destination : Path
        Directory receiving rendered files.
    source_stem : str
        Stem used for output filenames.
    formats : tuple[str, ...]
        Requested output formats.
    width : int
        Render width in pixels.
    scale : float
        Render scale.

    Raises
    ------
    MermaidError
        If Mermaid Ink rejects a render request.
    """
    server = os.getenv('MERMAID_INK_SERVER', 'https://mermaid.ink').rstrip('/')
    encoded_source = _encode_compressed_payload(source_text)

    with httpx.Client(timeout=MERMAID_INK_TIMEOUT_SECONDS) as client:
        for output_format in formats:
            endpoint = 'svg' if output_format == 'svg' else 'img'
            params: dict[str, int | float | str] = {
                'width': width,
                'scale': scale,
            }
            if output_format == 'png':
                params['format'] = 'png'

            url = f'{server}/{endpoint}/{encoded_source}'
            response = client.get(url, params=params)
            if not response.is_success:
                raise MermaidError(
                    response.status_code, response.text, str(response.url)
                )

            output_path = destination / f'{source_stem}.{output_format}'
            if output_format == 'svg':
                output_path.write_text(response.text, encoding='utf-8')
            else:
                output_path.write_bytes(response.content)
            console.print(f'[green]Rendered[/green] {output_path}')


def _render(
    source: Path,
    output_dir: Path | None,
    formats: tuple[str, ...],
    width: int,
    scale: float,
) -> None:
    destination = output_dir or source.parent
    destination.mkdir(parents=True, exist_ok=True)
    _render_with_compressed_api(
        source.read_text(encoding='utf-8'),
        destination,
        source.stem,
        formats,
        width,
        scale,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Render selected Mermaid diagrams.

    Parameters
    ----------
    argv : Sequence[str] | None
        Optional command-line arguments. When omitted, arguments come from
        ``sys.argv``.

    Returns
    -------
    int
        Process exit status.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    sources = _collect_sources(arguments.sources)
    if not sources:
        parser.error('No Mermaid source files were found.')

    for source in sources:
        _render(
            source,
            arguments.output_dir,
            _formats(arguments.output_format),
            arguments.width,
            arguments.scale,
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

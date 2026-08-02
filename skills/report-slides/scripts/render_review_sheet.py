"""Compose labeled raster previews into a visual review sheet."""

import argparse
import math
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageOps


GAP: int = 8
HEADER_HEIGHT: int = 28
BACKGROUND: Tuple[int, int, int] = (245, 247, 250)
SUPPORTED_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png"})


def compose_review_sheet(
    input_paths: Sequence[Path],
    output_path: Path,
    *,
    columns: int = 2,
    cell_width: int = 600,
    cell_height: int = 338,
) -> Path:
    """Compose labeled PNG or JPEG previews into a raster review sheet.

    Args:
        input_paths: Already-rendered PNG or JPEG files to include.
        output_path: Destination path for the composed review sheet.
        columns: Number of preview columns in the sheet.
        cell_width: Width of each preview cell in pixels.
        cell_height: Height of each preview cell in pixels.

    Returns:
        The destination path after the review sheet is written.

    Raises:
        FileNotFoundError: If an input path does not exist.
        ValueError: If inputs or geometry are invalid, or an input extension is
            not PNG or JPEG.
        OSError: If Pillow cannot decode an input or write the output.
    """
    paths = [Path(input_path) for input_path in input_paths]
    if not paths:
        raise ValueError("at least one input image is required")
    if columns <= 0:
        raise ValueError("columns must be positive")
    if cell_width <= 0:
        raise ValueError("cell_width must be positive")
    if cell_height <= 0:
        raise ValueError("cell_height must be positive")

    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"input image not found: {path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"unsupported input extension for {path}: expected PNG or JPEG"
            )

    previews: List[Image.Image] = []
    for path in paths:
        with Image.open(path) as decoded_image:
            preview = ImageOps.contain(
                decoded_image.convert("RGB"),
                (cell_width, cell_height),
            )
            previews.append(preview.copy())

    rows = math.ceil(len(paths) / columns)
    sheet_width = columns * cell_width + (columns + 1) * GAP
    sheet_height = (
        GAP
        + rows * (HEADER_HEIGHT + cell_height + GAP)
        + GAP // 2
    )
    sheet = Image.new("RGB", (sheet_width, sheet_height), BACKGROUND)
    drawing = ImageDraw.Draw(sheet)

    for index, (path, preview) in enumerate(zip(paths, previews)):
        row, column = divmod(index, columns)
        cell_x = GAP + column * (cell_width + GAP)
        cell_y = GAP + row * (HEADER_HEIGHT + cell_height + GAP)
        drawing.rectangle(
            (
                cell_x,
                cell_y,
                cell_x + cell_width - 1,
                cell_y + HEADER_HEIGHT - 1,
            ),
            fill=(231, 235, 240),
        )
        drawing.text(
            (cell_x + GAP // 2, cell_y + GAP // 2),
            path.name,
            fill=(25, 31, 38),
        )
        preview_x = cell_x + (cell_width - preview.width) // 2
        preview_y = (
            cell_y
            + HEADER_HEIGHT
            + (cell_height - preview.height) // 2
        )
        sheet.paste(preview, (preview_x, preview_y))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def _positive_integer(value: str) -> int:
    """Parse a strictly positive integer CLI argument."""
    try:
        integer_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if integer_value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return integer_value


def _parse_arguments(arguments: Optional[Sequence[str]]) -> argparse.Namespace:
    """Parse review-sheet command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Compose PNG and JPEG files into a visual review sheet."
    )
    parser.add_argument(
        "--input",
        dest="input_paths",
        action="append",
        required=True,
        type=Path,
        help="Input PNG or JPEG file; repeat this option for each file.",
    )
    parser.add_argument(
        "--out",
        dest="output_path",
        required=True,
        type=Path,
        help="Output review-sheet path.",
    )
    parser.add_argument(
        "--columns",
        type=_positive_integer,
        default=2,
        help="Number of columns (default: 2).",
    )
    parser.add_argument(
        "--cell-width",
        type=_positive_integer,
        default=600,
        help="Preview-cell width in pixels (default: 600).",
    )
    parser.add_argument(
        "--cell-height",
        type=_positive_integer,
        default=338,
        help="Preview-cell height in pixels (default: 338).",
    )
    return parser.parse_args(arguments)


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """Run the review-sheet command-line interface.

    Args:
        arguments: Optional argument sequence; defaults to ``sys.argv``.

    Returns:
        Zero on success, or one when composition or output fails.
    """
    parsed = _parse_arguments(arguments)
    try:
        compose_review_sheet(
            parsed.input_paths,
            parsed.output_path,
            columns=parsed.columns,
            cell_width=parsed.cell_width,
            cell_height=parsed.cell_height,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: review sheet written to {parsed.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

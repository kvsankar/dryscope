"""Document parsing and chunking."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import mistune

from dryscope.docs.models import Chunk, Document


def detect_boilerplate_headings(
    chunks: list[Chunk],
    num_documents: int,
    frequency_threshold: float = 0.3,
) -> set[str]:
    """Detect headings that appear in many documents (likely boilerplate).

    Returns normalized leaf-heading strings that appear in >= frequency_threshold
    fraction of documents.
    """
    heading_docs: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        if chunk.heading_path:
            leaf = chunk.heading_path[-1].lower().strip()
            heading_docs[leaf].add(chunk.document_path)

    threshold_count = max(3, num_documents * frequency_threshold)
    return {h for h, docs in heading_docs.items() if len(docs) >= threshold_count}


def _extract_heading_text(node: dict[str, Any]) -> str:
    """Extract plain text from a heading AST node."""
    parts: list[str] = []
    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue
        if "raw" in child:
            parts.append(child["raw"])
        elif "children" in child:
            parts.append(_extract_heading_text(child))
    return "".join(parts)


def _heading_prefix(level: int) -> str:
    """Return markdown heading prefix like '##'."""
    return "#" * level


def _markdown_headings(ast_nodes: list[Any]) -> list[tuple[int, str, int]]:
    """Extract markdown headings from a mistune AST."""
    headings: list[tuple[int, str, int]] = []
    for i, node in enumerate(ast_nodes):
        if not isinstance(node, dict):
            continue
        if node.get("type") != "heading":
            continue
        raw_attrs = node.get("attrs")
        attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
        level = int(attrs.get("level", 1))
        headings.append((level, _extract_heading_text(node), i))
    return headings


def _heading_source_lines(
    headings: list[tuple[int, str, int]],
    lines: list[str],
) -> list[int]:
    """Map each heading AST entry back to its source line index."""
    heading_lines: list[int] = []
    search_from = 0
    for level, h_text, _ in headings:
        prefix = _heading_prefix(level) + " "
        for line_idx in range(search_from, len(lines)):
            line = lines[line_idx]
            if line.startswith(prefix) and h_text in line:
                heading_lines.append(line_idx)
                search_from = line_idx + 1
                break
        else:
            heading_lines.append(search_from)
    return heading_lines


def _single_markdown_chunk(text: str, file_path: str, total_lines: int) -> list[Chunk]:
    """Return one chunk for a heading-free markdown document."""
    content = text.strip()
    if not content:
        return []
    return [
        Chunk(
            document_path=file_path,
            heading_path=[],
            content=content,
            line_start=1,
            line_end=total_lines,
        )
    ]


def _markdown_sections(
    headings: list[tuple[int, str, int]],
    heading_lines: list[int],
    lines: list[str],
) -> list[tuple[list[str], int, int]]:
    """Build heading-path sections from source heading locations."""
    sections: list[tuple[list[str], int, int]] = []
    heading_stack: list[tuple[int, str]] = []
    total_lines = len(lines)

    first_heading_line = heading_lines[0]
    if first_heading_line > 0:
        pre_content = "\n".join(lines[:first_heading_line]).strip()
        if pre_content:
            sections.append(([], 1, first_heading_line))

    for i, (level, h_text, _ast_idx) in enumerate(headings):
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, h_text))

        heading_path = [f"{'#' * lvl} {txt}" for lvl, txt in heading_stack]
        line_start = heading_lines[i] + 1
        line_end = heading_lines[i + 1] if i + 1 < len(headings) else total_lines
        sections.append((heading_path, line_start, line_end))

    return sections


def _chunks_from_sections(
    sections: list[tuple[list[str], int, int]],
    lines: list[str],
    file_path: str,
) -> list[Chunk]:
    """Convert section boundaries into non-empty Chunk objects."""
    chunks: list[Chunk] = []
    for heading_path, line_start, line_end in sections:
        content = "\n".join(lines[line_start - 1 : line_end]).strip()
        if content:
            chunks.append(
                Chunk(
                    document_path=file_path,
                    heading_path=list(heading_path),
                    content=content,
                    line_start=line_start,
                    line_end=line_end,
                )
            )
    return chunks


def chunk_markdown(text: str, file_path: str) -> list[Chunk]:
    """Split markdown text into chunks by headings using mistune AST.

    Each chunk corresponds to a section under a heading. Content before the
    first heading becomes a chunk with an empty heading path.
    """
    md = mistune.create_markdown(renderer="ast")
    raw_ast_nodes = md(text)
    ast_nodes = raw_ast_nodes if isinstance(raw_ast_nodes, list) else []

    lines = text.split("\n")
    total_lines = len(lines)

    headings = _markdown_headings(ast_nodes)
    if not headings:
        return _single_markdown_chunk(text, file_path, total_lines)

    heading_lines = _heading_source_lines(headings, lines)
    sections = _markdown_sections(headings, heading_lines, lines)
    return _chunks_from_sections(sections, lines, file_path)


def chunk_plaintext(text: str, file_path: str) -> list[Chunk]:
    """Split plain text into chunks by paragraph breaks (double newlines)."""
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[Chunk] = []
    current_line = 1

    for para in paragraphs:
        content = para.strip()
        if not content:
            current_line += para.count("\n") + 1
            continue
        line_count = content.count("\n") + 1
        chunks.append(
            Chunk(
                document_path=file_path,
                heading_path=[],
                content=content,
                line_start=current_line,
                line_end=current_line + line_count - 1,
            )
        )
        # Advance past this paragraph plus the blank line(s)
        current_line += para.count("\n") + 2  # +2 for the split delimiter

    return chunks


def chunk_file(file_path: Path) -> list[Chunk]:
    """Read and chunk a single file."""
    text = file_path.read_text(encoding="utf-8", errors="replace")
    path_str = str(file_path)

    if file_path.suffix.lower() in (".md", ".markdown", ".mdx"):
        return chunk_markdown(text, path_str)
    else:
        return chunk_plaintext(text, path_str)


def _is_doc_excluded(path: Path, root: Path, exclude_patterns: list[str]) -> bool:
    """Check if a path matches any exclude pattern."""
    rel = path.relative_to(root)
    name = rel.name
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(str(rel), pattern) or fnmatch.fnmatch(name, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in rel.parent.parts):
            return True
    return False


def discover_files(
    root: Path,
    include: list[str],
    exclude: list[str],
) -> list[Path]:
    """Find all documentation files under root matching include/exclude globs.

    Tries git ls-files first for speed and to skip untracked junk,
    then falls back to rglob + fnmatch if not in a git repo.
    """
    # Try git-tracked files first
    git_files = _get_git_tracked_files(root, include)
    if git_files is not None:
        # Apply exclude filters to git results
        return [path for path in git_files if not _is_doc_excluded(path, root, exclude)]

    # Fallback: rglob discovery
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        if _is_doc_excluded(path, root, exclude):
            continue

        rel = str(path.relative_to(root))

        # Check includes
        included = False
        for pattern in include:
            if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel, pattern):
                included = True
                break
        if not included:
            continue

        files.append(path)

    return files


def chunk_documents(
    root: Path,
    include: list[str],
    exclude: list[str],
) -> list[Document]:
    """Discover and chunk all documents under root."""
    files = discover_files(root, include, exclude)
    documents: list[Document] = []

    for file_path in files:
        chunks = chunk_file(file_path)
        if chunks:
            documents.append(Document(path=str(file_path), chunks=chunks))

    return documents


def chunk_file_list(file_paths: list[Path], root: Path) -> list[Document]:
    """Chunk an explicit list of files. No discovery, no filtering.

    Relative paths are resolved against root first; if not found,
    falls back to resolving against CWD.
    """
    documents: list[Document] = []
    for file_path in file_paths:
        if file_path.is_absolute():
            resolved = file_path
        else:
            # Try root first, then CWD
            candidate = (root / file_path).resolve()
            if candidate.is_file():
                resolved = candidate
            else:
                resolved = file_path.resolve()
        if not resolved.is_file():
            continue
        chunks = chunk_file(resolved)
        if chunks:
            documents.append(Document(path=str(resolved), chunks=chunks))
    return documents


def _get_git_tracked_files(root: Path, include: list[str]) -> list[Path] | None:
    """Run git ls-files filtered by include globs. Returns None if not a git repo."""
    try:
        cmd = ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"]
        for pattern in include:
            cmd.append(pattern)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return None
        paths = []
        for line in proc.stdout.strip().splitlines():
            if line:
                paths.append(root / line)
        return sorted(paths)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

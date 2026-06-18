"""
MkDocs hook to add automatic section numbering to user-guide pages.

This hook processes markdown content before rendering to add chapter and section
numbers based on filename prefixes (e.g., 00-getting-started.md becomes Chapter 1).

The numbering is applied only during HTML generation and does not modify source files.
"""

import re
from pathlib import Path


def on_page_markdown(markdown, page, config, files):
    """
    Hook called by MkDocs before markdown is converted to HTML.
    
    Adds section numbering to user-guide pages based on:
    - Chapter number derived from filename prefix (00 -> 1, 01 -> 2, etc.)
    - Section numbers for ## headers (1.1, 1.2, etc.)
    - Subsection numbers for ### headers (1.1.1, 1.1.2, etc.)
    """
    # Only process files in the user-guide directory
    if not page.file.src_path.startswith('user-guide/'):
        return markdown
    
    # Extract the chapter number from the filename
    # e.g., "00-getting-started.md" -> chapter 1
    #       "01-configuration.md" -> chapter 2
    filename = Path(page.file.src_path).name
    match = re.match(r'^(\d+)-', filename)
    
    if not match:
        return markdown
    
    file_number = int(match.group(1))
    chapter_number = file_number + 1  # 00 becomes 1, 01 becomes 2, etc.
    
    # Process the markdown line by line
    lines = markdown.split('\n')
    processed_lines = []
    
    section_counter = 0
    subsection_counter = 0
    subsubsection_counter = 0
    in_code_block = False
    
    for line in lines:
        # Track code blocks to avoid processing headers inside them
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            processed_lines.append(line)
            continue
        
        if in_code_block:
            processed_lines.append(line)
            continue
        
        # Process headers
        # Main page title (# Header) - add chapter number
        if line.startswith('# ') and not line.startswith('## '):
            title = line[2:].strip()
            processed_lines.append(f'# {chapter_number}. {title}')
            section_counter = 0
            subsection_counter = 0
            subsubsection_counter = 0
        
        # Second-level headers (## Header) - add section number
        elif line.startswith('## ') and not line.startswith('### '):
            section_counter += 1
            subsection_counter = 0
            subsubsection_counter = 0
            title = line[3:].strip()
            processed_lines.append(f'## {chapter_number}.{section_counter}. {title}')
        
        # Third-level headers (### Header) - add subsection number
        elif line.startswith('### ') and not line.startswith('#### '):
            subsection_counter += 1
            subsubsection_counter = 0
            title = line[4:].strip()
            processed_lines.append(f'### {chapter_number}.{section_counter}.{subsection_counter}. {title}')
        
        # Fourth-level headers (#### Header) - add subsubsection number
        elif line.startswith('#### ') and not line.startswith('##### '):
            subsubsection_counter += 1
            title = line[5:].strip()
            processed_lines.append(f'#### {chapter_number}.{section_counter}.{subsection_counter}.{subsubsection_counter}. {title}')
        
        else:
            processed_lines.append(line)
    
    return '\n'.join(processed_lines)

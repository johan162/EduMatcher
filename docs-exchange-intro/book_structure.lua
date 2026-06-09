-- book_structure.lua
-- Enforce textbook-style structure for the Exchange Intro build:
-- - Front matter prose before Part I
-- - Four \part blocks
-- - Consecutive chapter numbering across parts
-- - Back matter for Glossary and References

local function tex_escape(text)
  return text
    :gsub("\\", "\\textbackslash{}")
    :gsub("([%%#&{}_])", "\\%1")
end

local function heading_text(el)
  return pandoc.utils.stringify(el.content)
end

local skipping_embedded_toc = false
local in_part = false
local mainmatter_started = false
local backmatter_started = false
local preface_started = false

local function emit_raw(line)
  return pandoc.RawBlock("latex", line)
end

local function is_part_heading(text)
  return text:match("^Part%s+[IVXLC]+%s*:%s*") ~= nil
end

local function is_glossary_or_references(text)
  return text == "Glossary" or text == "References"
end

function Header(el)
  local text = heading_text(el)

  -- Drop the top document title because the LaTeX template already provides one.
  if el.level == 1 and text == "How a Financial Exchange Works" then
    return {}
  end

  -- Drop the hand-written TOC section from source markdown.
  if el.level == 1 and text == "Table of Contents" then
    skipping_embedded_toc = true
    return {}
  end

  -- Keep skipping until first part heading appears.
  if skipping_embedded_toc and el.level == 1 and is_part_heading(text) then
    skipping_embedded_toc = false
  elseif skipping_embedded_toc then
    return {}
  end

  -- Render Preface as unnumbered front-matter chapter.
  if el.level == 1 and text == "Preface" then
    preface_started = true
    in_part = false
    return {
      emit_raw("\\chapter*{Preface}"),
      emit_raw("\\addcontentsline{toc}{chapter}{Preface}")
    }
  end

  -- Start main matter at first part, then render parts explicitly.
  if el.level == 1 and is_part_heading(text) then
    in_part = true
    local blocks = pandoc.List()
    if not mainmatter_started then
      blocks:insert(emit_raw("\\mainmatter"))
      mainmatter_started = true
    end
    blocks:insert(emit_raw("\\part{" .. tex_escape(text) .. "}"))
    return blocks
  end

  -- Start back matter and render Glossary/References as unnumbered chapters.
  if el.level == 1 and is_glossary_or_references(text) then
    in_part = false
    local blocks = pandoc.List()
    if not backmatter_started then
      blocks:insert(emit_raw("\\backmatter"))
      blocks:insert(emit_raw("\\setcounter{secnumdepth}{-1}"))
      backmatter_started = true
    end
    blocks:insert(emit_raw("\\chapter*{" .. tex_escape(text) .. "}"))
    blocks:insert(emit_raw("\\addcontentsline{toc}{chapter}{" .. tex_escape(text) .. "}"))
    return blocks
  end

  return nil
end

function BulletList(el)
  if not preface_started and not mainmatter_started then
    return {}
  end
  if skipping_embedded_toc then
    return {}
  end
  return nil
end

function OrderedList(el)
  if not preface_started and not mainmatter_started then
    return {}
  end
  if skipping_embedded_toc then
    return {}
  end
  return nil
end

function Para(el)
  if not preface_started and not mainmatter_started then
    return {}
  end
  if skipping_embedded_toc then
    return {}
  end
  return nil
end

function Plain(el)
  if not preface_started and not mainmatter_started then
    return {}
  end
  if skipping_embedded_toc then
    return {}
  end
  return nil
end

function RawBlock(el)
  if not preface_started and not mainmatter_started then
    return {}
  end
  if skipping_embedded_toc then
    return {}
  end
  return nil
end

function BlockQuote(el)
  if not preface_started and not mainmatter_started then
    return {}
  end
  if skipping_embedded_toc then
    return {}
  end
  if #el.content == 0 then
    return {}
  end
  return nil
end

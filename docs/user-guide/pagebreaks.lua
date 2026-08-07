-- pagebreaks.lua
-- Conditional page breaks for pandoc → LaTeX User Guide builds.
--
-- Usage:
--   pandoc --lua-filter pagebreaks.lua --metadata paper_format=b5 ...
--
-- Between-block page breaks (HTML comments in markdown):
--   <!-- pagebreak:any -->   fires for every format
--   <!-- pagebreak:a4 -->    fires for A4 builds only
--   <!-- pagebreak:b5 -->    fires for B5 builds only
--
-- Legacy fenced-div markers are still supported by the filter for PDF builds,
-- but should not be used in MkDocs-rendered pages because they collide with
-- mkdocstrings collection syntax.
--
-- Inside code-block breaks:
--   !!! yaml-cbreak-a4       fires for A4 builds only
--   !!! text-cbreak-b5       fires for B5 builds only
--
-- The prefix before -cbreak- sets the language class of the code block that
-- follows the break (e.g. yaml, text, toml) for correct syntax highlighting.
-- Marker lines are always stripped from the output; a \newpage is inserted
-- only for the active format.  In non-LaTeX output all markers are just removed.
--
-- Implementation note: pandoc's Lua filter traversal is bottom-up, so a plain
-- Meta function would run AFTER CodeBlock functions, leaving paper_format nil.
-- We use a Pandoc function instead, which receives the full document and lets
-- us read metadata before walking any elements.

local function newpage()
  return pandoc.RawBlock("latex", "\\newpage")
end

local PAGEBREAK_COMMENT_ANY = "^%s*<!%-%-%s*pagebreak%s*%-%->%s*$"
local PAGEBREAK_COMMENT_FMT = "^%s*<!%-%-%s*pagebreak:([%w_]+)%s*%-%->%s*$"

local function is_active_marker(marker_format, paper_format)
  return marker_format == nil
      or marker_format == ""
      or marker_format == "any"
      or marker_format == paper_format
end

local function comment_marker_format(raw)
  if raw:match(PAGEBREAK_COMMENT_ANY) then
    return "any"
  end
  return raw:match(PAGEBREAK_COMMENT_FMT)
end

local function emit_comment_pagebreak(raw, paper_format)
  local marker_format = comment_marker_format(raw)
  if not marker_format then
    return nil
  end
  if FORMAT == "latex" and is_active_marker(marker_format, paper_format) then
    return newpage()
  end
  return {}
end

-- ──────────────────────────────────────────────────────────────────────────────
-- Between-block page breaks via fenced divs (legacy support)
--
-- Required syntax — the closing ::: is mandatory:
--   ::: pagebreak
--   :::
--
-- If the closing ::: is accidentally omitted, pandoc parses everything
-- that follows as children of the div.  The handler always re-emits
-- el.content after the \newpage so that the document is never truncated.
-- ──────────────────────────────────────────────────────────────────────────────
local function make_div_filter(paper_format)
  return function(el)
    local function emit(active)
      if active then
        if FORMAT == "latex" then
          -- Prepend \newpage; re-emit any children so a missing ::: is safe.
          local result = pandoc.List({newpage()})
          result:extend(el.content)
          return result
        else
          return el.content  -- non-latex: strip the div tag, keep content
        end
      else
        return el.content    -- wrong format: strip the div tag, keep content
      end
    end

    for _, class in ipairs(el.classes) do
      if class == "pagebreak" then
        return emit(true)
      elseif class == "pagebreak-" .. paper_format then
        return emit(true)
      elseif class:match("^pagebreak%-") then
        return emit(false)
      end
    end
  end
end

-- ──────────────────────────────────────────────────────────────────────────────
-- Between-block page breaks via HTML comments
--
-- Preferred syntax for source shared between MkDocs HTML and Pandoc PDF builds:
--   <!-- pagebreak:any -->
--   <!-- pagebreak:a4 -->
--   <!-- pagebreak:b5 -->
--
-- MkDocs ignores these comments, while Pandoc exposes them as raw HTML blocks
-- or raw HTML inlines that we can translate to \newpage for LaTeX output.
-- ──────────────────────────────────────────────────────────────────────────────
local function make_rawblock_filter(paper_format)
  return function(el)
    if el.format ~= "html" then
      return nil
    end
    return emit_comment_pagebreak(el.text, paper_format)
  end
end

local function make_paragraph_filter(paper_format)
  return function(el)
    if #el.content ~= 1 then
      return nil
    end
    local child = el.content[1]
    if child.t ~= "RawInline" or child.format ~= "html" then
      return nil
    end
    return emit_comment_pagebreak(child.text, paper_format)
  end
end

-- ──────────────────────────────────────────────────────────────────────────────
-- Internal chapter-link rewrites for concatenated PDF builds
--
-- User Guide and Training PDF builds concatenate many markdown files into one
-- Pandoc document. Links like `040-running-the-exchange.md#running-the-exchange`
-- are therefore intra-document links, but Pandoc treats them as file links by
-- default. For LaTeX output we rewrite these to `#running-the-exchange` when the
-- target anchor exists in the current document.
--
-- This is intentionally conservative:
--   - only markdown file links are considered
--   - only rewritten when the destination anchor is known in this document
--   - external URLs and unknown anchors are left unchanged
-- ──────────────────────────────────────────────────────────────────────────────
local function split_target(target)
  local path, fragment = target:match("^([^#]+)#(.+)$")
  if path then
    return path, fragment
  end
  return target, nil
end

local function trim_path_separators(path)
  return path:gsub("^%s+", ""):gsub("%s+$", "")
end

local function normalize_path(path)
  local is_abs = path:sub(1, 1) == "/"
  local parts = {}
  for part in path:gmatch("[^/]+") do
    if part == "." or part == "" then
      -- skip
    elseif part == ".." then
      if #parts > 0 and parts[#parts] ~= ".." then
        table.remove(parts)
      elseif not is_abs then
        table.insert(parts, "..")
      end
    else
      table.insert(parts, part)
    end
  end
  local joined = table.concat(parts, "/")
  if is_abs then
    return "/" .. joined
  end
  return joined
end

local function join_paths(base, rel)
  if rel:sub(1, 1) == "/" then
    return normalize_path(rel)
  end
  if base == "" then
    return normalize_path(rel)
  end
  return normalize_path(base .. "/" .. rel)
end

local function file_exists(path)
  local fh = io.open(path, "r")
  if fh then
    fh:close()
    return true
  end
  return false
end

local function is_markdown_path(path)
  if not path or path == "" then
    return false
  end
  path = path:gsub("%?.*$", "")
  if path:match("^[%a][%w+.-]*:") then
    return false
  end
  return path:match("%.md$") ~= nil or path:match("%.markdown$") ~= nil
end

local function resolve_existing_markdown(path)
  local clean = trim_path_separators(path:gsub("%?.*$", ""))
  local candidates = {
    -- Paths that work when pandoc is run from docs/ (make -C docs ...).
    normalize_path(clean),
    join_paths("user-guide", clean),
    join_paths("training", clean),

    -- Paths that work when pandoc is run from repository root.
    join_paths("docs/user-guide", clean),
    join_paths("docs/training", clean),
    join_paths("docs", clean),

    -- Fallbacks when cwd is a nested build directory.
    join_paths("../user-guide", clean),
    join_paths("../training", clean),
    join_paths("../docs/user-guide", clean),
    join_paths("../docs/training", clean),
  }

  for _, candidate in ipairs(candidates) do
    if candidate ~= "" and file_exists(candidate) then
      return candidate
    end
  end

  return nil
end

local first_anchor_cache = {}
local first_header_text_cache = {}

local function first_header_anchor_for_markdown(path)
  local resolved = resolve_existing_markdown(path)
  if not resolved then
    return nil
  end

  if first_anchor_cache[resolved] ~= nil then
    return first_anchor_cache[resolved]
  end

  local fh = io.open(resolved, "r")
  if not fh then
    first_anchor_cache[resolved] = false
    return nil
  end

  local markdown = fh:read("*a")
  fh:close()

  local parsed = pandoc.read(markdown, "markdown")
  for _, block in ipairs(parsed.blocks) do
    if block.t == "Header" and block.identifier and block.identifier ~= "" then
      first_anchor_cache[resolved] = block.identifier
      return block.identifier
    end
  end

  first_anchor_cache[resolved] = false
  return nil
end

local function first_header_text_for_markdown(path)
  local resolved = resolve_existing_markdown(path)
  if not resolved then
    return nil
  end

  if first_header_text_cache[resolved] ~= nil then
    return first_header_text_cache[resolved]
  end

  local fh = io.open(resolved, "r")
  if not fh then
    first_header_text_cache[resolved] = false
    return nil
  end

  local markdown = fh:read("*a")
  fh:close()

  local parsed = pandoc.read(markdown, "markdown")
  for _, block in ipairs(parsed.blocks) do
    if block.t == "Header" then
      local title = pandoc.utils.stringify(block.content)
      if title and title ~= "" then
        first_header_text_cache[resolved] = title
        return title
      end
      break
    end
  end

  first_header_text_cache[resolved] = false
  return nil
end

local function make_link_filter(known_anchors, h1_ids_by_title)
  return function(el)
    if FORMAT ~= "latex" then
      return nil
    end

    local path, fragment = split_target(el.target)
    if not is_markdown_path(path) then
      return nil
    end

    if fragment and known_anchors[fragment] then
      el.target = "#" .. fragment
      return el
    end

    if not fragment then
      local first_anchor = first_header_anchor_for_markdown(path)
      if first_anchor and known_anchors[first_anchor] then
        el.target = "#" .. first_anchor
        return el
      end

      -- If merged-doc IDs were suffixed for uniqueness (e.g. "processes-1"),
      -- resolve by matching the target chapter's first H1 title.
      local first_title = first_header_text_for_markdown(path)
      local merged_h1_id = first_title and h1_ids_by_title[first_title] or nil
      if merged_h1_id and merged_h1_id ~= "" then
        el.target = "#" .. merged_h1_id
        return el
      end
    end

    return nil
  end
end

-- ──────────────────────────────────────────────────────────────────────────────
-- Inside-code-block conditional breaks
--
-- Recognises lines of the form (anywhere inside a fenced code block):
--   !!! <lang>-cbreak-<format>
--
-- <lang>   — the language identifier to apply to the code block that FOLLOWS
--            the break (e.g. yaml, text, toml).  It is used to set the syntax-
--            highlighting class of the new sub-block, so it must match the
--            intended language of the content after the split.
-- <format> — the paper format that activates this break (a4 or b5).
--
-- The CodeBlock handler splits the block at active-format markers and strips
-- all other format markers.  Multiple CodeBlocks are returned interleaved with
-- \newpage RawBlocks when a split occurs.  Each sub-block receives the language
-- class from the marker that introduced it; the first sub-block keeps the
-- original block's language class.
-- ──────────────────────────────────────────────────────────────────────────────
local CBREAK = "^%s*!!!%s+(.-)%-cbreak%-([%w_]+)%s*$"

local function make_codeblock_filter(paper_format)
  return function(el)
    local orig_lang = el.classes[1] or ""
    local segments = {{lang = orig_lang, lines = {}}}
    local has_marker = false

    for line in (el.text .. "\n"):gmatch("([^\n]*)\n") do
      local lang, fmt = line:match(CBREAK)
      if lang and fmt then
        has_marker = true
        if fmt == paper_format and FORMAT == "latex" then
          -- Start a new segment; the prefix sets its language class.
          table.insert(segments, {lang = lang, lines = {}})
        end
        -- Always strip the marker line from the output.
      else
        table.insert(segments[#segments].lines, line)
      end
    end

    if not has_marker then return nil end  -- block unchanged

    if #segments == 1 then
      -- Markers were stripped but no split occurred (inactive format).
      el.text = table.concat(segments[1].lines, "\n")
      return el
    end

    local result = pandoc.List()
    for i, seg in ipairs(segments) do
      if i > 1 then result:insert(newpage()) end
      local cb = el:clone()
      cb.text = table.concat(seg.lines, "\n")
      -- Apply the language class from the marker prefix.
      if seg.lang ~= "" then
        cb.classes[1] = seg.lang
      else
        cb.classes = pandoc.List()
      end
      result:insert(cb)
    end
    return result
  end
end

-- ──────────────────────────────────────────────────────────────────────────────
-- Top-level Pandoc function — runs before any element walking, so metadata is
-- available when Div and CodeBlock handlers are called.
-- ──────────────────────────────────────────────────────────────────────────────
function Pandoc(doc)
  local paper_format = ""
  if doc.meta.paper_format then
    paper_format = pandoc.utils.stringify(doc.meta.paper_format)
  end

  local known_anchors = {}
  local h1_ids_by_title = {}
  doc:walk({
    Header = function(el)
      if el.identifier and el.identifier ~= "" then
        known_anchors[el.identifier] = true
        if el.level == 1 then
          local title = pandoc.utils.stringify(el.content)
          if title and title ~= "" and not h1_ids_by_title[title] then
            h1_ids_by_title[title] = el.identifier
          end
        end
      end
      return nil
    end,
  })

  return doc:walk({
    RawBlock  = make_rawblock_filter(paper_format),
    Para      = make_paragraph_filter(paper_format),
    Div       = make_div_filter(paper_format),
    CodeBlock = make_codeblock_filter(paper_format),
    Link      = make_link_filter(known_anchors, h1_ids_by_title),
  })
end

-- admonitions.lua
-- Convert MkDocs-style admonitions to LaTeX tcolorbox blocks.
--
-- Supported syntax:
--   !!! tip "Title"
--       Body text
--
--   !!! warning "Title"
--       Body text
--
--   !!! info "Title"
--       Body text
--
--   !!! note "Title"
--       Body text
--
-- Notes:
-- - This filter targets LaTeX output only.
-- - Requires \usepackage[most]{tcolorbox} in the LaTeX template preamble.

local STYLE = {
  note = {
    label = "Note",
    colback = "blue!4",
    colframe = "blue!55!black",
  },
  tip = {
    label = "Tip",
    colback = "green!8",
    colframe = "green!55!black",
  },
  warning = {
    label = "Warning",
    colback = "red!8",
    colframe = "red!65!black",
  },
  info = {
    label = "Info",
    colback = "black!5",
    colframe = "black!65",
  },
}

local function trim(s)
  return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function starts_with(s, prefix)
  return s:sub(1, #prefix) == prefix
end

local function inlines_after_first_linebreak(inlines)
  for i, inline in ipairs(inlines) do
    if inline.t == "SoftBreak" or inline.t == "LineBreak" then
      local rest = pandoc.List()
      for j = i + 1, #inlines do
        rest:insert(inlines[j])
      end
      return rest
    end
  end
  return pandoc.List()
end

local function parse_admonition_header(inlines)
  if #inlines < 3 then
    return nil
  end
  if inlines[1].t ~= "Str" or inlines[1].text ~= "!!!" then
    return nil
  end

  local first_break = nil
  for i, inline in ipairs(inlines) do
    if inline.t == "SoftBreak" or inline.t == "LineBreak" then
      first_break = i
      break
    end
  end

  local header_end = first_break and (first_break - 1) or #inlines
  local header_tokens = pandoc.List()
  for i = 2, header_end do
    header_tokens:insert(inlines[i])
  end

  local kind = nil
  local title = nil

  for _, tok in ipairs(header_tokens) do
    if not kind and tok.t == "Str" then
      kind = tok.text:lower()
    elseif not title and tok.t == "Quoted" then
      title = pandoc.utils.stringify(tok.content)
    end
  end

  if not kind or not STYLE[kind] then
    return nil
  end

  if not title or title == "" then
    title = STYLE[kind].label
  end

  return {
    kind = kind,
    title = title,
    inline_body = inlines_after_first_linebreak(inlines),
  }
end

local function parse_embedded_markdown_from_codeblock(block)
  if block.t ~= "CodeBlock" then
    return nil
  end
  -- Only try to parse code blocks with no language specified (indented content)
  if #block.classes > 0 then
    return nil
  end

  local ok, parsed = pcall(function()
    return pandoc.read(block.text, "markdown")
  end)
  if not ok then
    return nil
  end

  return parsed.blocks
end

-- Replace CodeBlocks with plain verbatim RawBlocks so the internal pandoc.write
-- call never emits \begin{Shaded}, which is only defined by Pandoc's default
-- template and not by our custom LaTeX templates.
local function decolor_codeblocks(blocks)
  return pandoc.walk_block(pandoc.Div(blocks), {
    CodeBlock = function(cb)
      return pandoc.RawBlock("latex",
        "\\begin{verbatim}\n" .. cb.text .. "\n\\end{verbatim}")
    end,
  }).content
end

local function latex_from_blocks(blocks)
  local body_doc = pandoc.Pandoc(decolor_codeblocks(blocks))
  local latex = pandoc.write(body_doc, "latex")
  return trim(latex)
end

local function split_target(target)
  local path, fragment = target:match("^([^#]+)#(.+)$")
  if path then
    return path, fragment
  end
  return target, nil
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

local function resolve_existing_markdown(path)
  local clean = trim(path:gsub("%?.*$", ""))
  local candidates = {
    normalize_path(clean),
    join_paths("user-guide", clean),
    join_paths("training", clean),
    join_paths("docs/user-guide", clean),
    join_paths("docs/training", clean),
    join_paths("docs", clean),
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

local function rewrite_internal_markdown_links(blocks, known_anchors, h1_ids_by_title)
  local rewritten = pandoc.walk_block(pandoc.Div(blocks), {
    Link = function(el)
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

        local first_title = first_header_text_for_markdown(path)
        local merged_h1_id = first_title and h1_ids_by_title[first_title] or nil
        if merged_h1_id and merged_h1_id ~= "" then
          el.target = "#" .. merged_h1_id
          return el
        end
      end

      return nil
    end,
  })

  return rewritten.content
end

local function build_tcolorbox(kind, title, body_latex)
  local style = STYLE[kind]
  local safe_title = title:gsub("([%%{}_$#&])", "\\%1")

  local options = table.concat({
    "enhanced",
    "breakable",
    "sharp corners=all",
    "arc=2.2mm",
    "boxrule=0.7pt",
    "left=1.2mm",
    "right=1.2mm",
    "top=0.9mm",
    "bottom=0.9mm",
    "colback=" .. style.colback,
    "colframe=" .. style.colframe,
    "coltitle=white",
    "fonttitle=\\bfseries\\sffamily",
    "title={" .. safe_title .. "}",
  }, ",")

  return table.concat({
    "\\begin{tcolorbox}[" .. options .. "]",
    body_latex,
    "\\end{tcolorbox}",
  }, "\n")
end

local function is_list_block(block)
  return block and (
    block.t == "BulletList" or
    block.t == "OrderedList" or
    block.t == "DefinitionList"
  )
end

local function is_richcontent_block(block)
  return block and (
    block.t == "BlockQuote" or
    block.t == "Table"
  )
end

function Pandoc(doc)
  if FORMAT ~= "latex" then
    return doc
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

  local out = pandoc.List()
  local i = 1

  while i <= #doc.blocks do
    local block = doc.blocks[i]

    if block.t == "Para" then
      local header = parse_admonition_header(block.content)
      if header then
        local body_blocks = pandoc.List()

        if #header.inline_body > 0 then
          body_blocks:insert(pandoc.Para(header.inline_body))
        end

        -- Collect immediately following blocks that belong to the admonition
        local collected = 0
        while i + 1 + collected <= #doc.blocks do
          local next_block = doc.blocks[i + 1 + collected]
          
          -- Stop at headers, horizontal rules, or other admonitions
          if next_block.t == "Header" or 
             next_block.t == "HorizontalRule" or
             (next_block.t == "Para" and parse_admonition_header(next_block.content)) then
            break
          end

          -- Try to parse embedded code as markdown
          local parsed = parse_embedded_markdown_from_codeblock(next_block)
          if parsed and #parsed > 0 then
            body_blocks:extend(parsed)
            collected = collected + 1
          -- Include lists, blockquotes, tables directly
          elseif is_list_block(next_block) or is_richcontent_block(next_block) then
            body_blocks:insert(next_block)
            collected = collected + 1
          -- Include paragraphs that follow (body content)
          elseif next_block.t == "Para" then
            body_blocks:insert(next_block)
            collected = collected + 1
          else
            break
          end
        end

        if #body_blocks > 0 then
          body_blocks = rewrite_internal_markdown_links(body_blocks, known_anchors, h1_ids_by_title)
          local body_latex = latex_from_blocks(body_blocks)
          out:insert(pandoc.RawBlock("latex", build_tcolorbox(header.kind, header.title, body_latex)))
        end

        i = i + 1 + collected
        goto continue
      end
    end

    out:insert(block)
    i = i + 1
    ::continue::
  end

  doc.blocks = out
  return doc
end

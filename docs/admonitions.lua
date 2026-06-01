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
-- Notes:
-- - This filter targets LaTeX output only.
-- - Requires \usepackage[most]{tcolorbox} in the LaTeX template preamble.

local STYLE = {
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
  if #block.classes > 0 then
    return nil
  end
  if not starts_with(block.text, "```") then
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

local function build_tcolorbox(kind, title, body_latex)
  local style = STYLE[kind]
  local safe_title = title:gsub("([%%{}])", "\\%1")

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

function Pandoc(doc)
  if FORMAT ~= "latex" then
    return doc
  end

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

        local next_block = doc.blocks[i + 1]
        local consumed_next = false
        if next_block then
          local parsed = parse_embedded_markdown_from_codeblock(next_block)
          if parsed and #parsed > 0 then
            body_blocks:extend(parsed)
            consumed_next = true
          end
        end

        if #body_blocks > 0 then
          local body_latex = latex_from_blocks(body_blocks)
          out:insert(pandoc.RawBlock("latex", build_tcolorbox(header.kind, header.title, body_latex)))
        end

        i = i + (consumed_next and 2 or 1)
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

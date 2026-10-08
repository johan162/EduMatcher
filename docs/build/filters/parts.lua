-- Turn a level-1 heading with class `part` into a book Part for LaTeX.
local count = 0
local romans = { "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X" }

function Header(el)
  if el.level ~= 1 or not el.classes:includes("part") then
    return nil
  end
  count = count + 1
  if FORMAT:match("latex") then
    local inlines = pandoc.List({ pandoc.RawInline("latex", "\\part{") })
    inlines:extend(el.content)
    inlines:insert(pandoc.RawInline("latex", "}"))
    return pandoc.Plain(inlines)
  end
  el.content:insert(1, pandoc.Str("Part " .. (romans[count] or tostring(count)) .. ": "))
  return el
end

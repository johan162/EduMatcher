-- Replace cross-book links with printable book/title text.
local function is_external(target)
  return target:match("^%w+:") or target:match("^//")
end

local function current_book(path)
  return path:match("docs/books/([^/]+)/")
end

local function target_book(target)
  return target:match("docs/books/([^/]+)/")
end

function Link(el)
  if FORMAT:match("html") or FORMAT == "epub3" then
    return nil
  end
  local target = el.target or ""
  if is_external(target) then
    return nil
  end
  local book = target_book(target)
  if not book or book == current_book(target) then
    return nil
  end
  local labels = {
    ["quick-start"] = "Quick Start Guide",
    ["participant-guide"] = "Participant Guide",
    ["operator-guide"] = "Operator's Guide",
    ["reference-manual"] = "Reference Manual",
    ["protocols-and-clients"] = "Protocols and Clients",
    ["architecture-and-development"] = "Architecture and Developer Guide",
    ["training-guide"] = "Training Guide",
  }
  local label = labels[book] or book
  return pandoc.Str(label)
end

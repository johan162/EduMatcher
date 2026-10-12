# latex-table-rules.awk — insert \tablerowrule (defined in latex-tables.tex)
# between the data rows of every Pandoc longtable in a LaTeX body.
#
# Pandoc's longtable layout is: head rows, \endhead, \bottomrule,
# \endlastfoot, body rows (each ending in "\\" at end of line), then
# \end{longtable}. The rule is emitted before each body row except the
# first, so it always follows a row end directly and never doubles up
# against \bottomrule after the last row.
/\\endlastfoot/      { print; body = 1; row_ended = 0; next }
/\\end\{longtable\}/ { print; body = 0; next }
body && row_ended && NF { print "\\tablerowrule"; row_ended = 0 }
body && /\\\\[[:space:]]*$/ { row_ended = 1 }
{ print }

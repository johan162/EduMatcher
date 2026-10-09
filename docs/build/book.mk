# Generic manifest-driven build rules for all EduMatcher books.

VARIANTS := a4 b5 dark_a4 dark_b5
LUA_FLAGS := --lua-filter $(FILTER_DIR)/parts.lua \
  --lua-filter $(FILTER_DIR)/pagebreaks.lua \
  --lua-filter $(FILTER_DIR)/admonitions.lua

shq = $(subst ','\'',$(1))

# A chapter links its images relative to itself (../../../assets/x.png) so the
# MkDocs site resolves them; the PDF/EPUB build symlinks assets/ beside book.md,
# so strip the leading ../ segments there.
NORMALISE_ASSETS = sed -i.bak -E 's@\]\((\.\./)+assets/@](assets/@g' $(1) && rm -f $(1).bak


define RUN_LATEX
printf '%b\n' "$(DARKYELLOW)  - Compiling $(BRIGHTCYAN)\"$(notdir $(2))\"$(DARKYELLOW) with $(BRIGHTCYAN)\"$(LATEX_ENGINE)\"$(DARKYELLOW)...$(NC)"
pushd $(1) >/dev/null
for pass in 1 2; do
  PATH="$(PATH):$(TEXBIN_FALLBACK)" TEXINPUTS="$(abspath $(BUILD_ASSETS))//:" \
    $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error \
    -output-directory . report.tex > xelatex-pass$$pass.log 2>&1 \
    || { printf '%b\n' "$(RED)ERROR LaTeX pass $$pass failed for $(BRIGHTCYAN)\"$(notdir $(2))\"$(NC)" >&2; tail -30 xelatex-pass$$pass.log >&2; exit 1; }
done
popd >/dev/null
endef


define RENDER_PDF
printf '%b\n' "$(DARKYELLOW)- Building $(BRIGHTCYAN)\"$(notdir $(5))\"$(DARKYELLOW) via LaTeX pipeline...$(NC)"
rm -rf $(1) && mkdir -p $(1)/expanded/.mermaid-img
# Absolute target: $(1)'s depth differs between whole-book and per-chapter builds.
ln -sfn $(abspath $(ASSETS_DIR)) $(1)/assets
printf '%b\n' "$(DARKYELLOW)  - Expanding shell command outputs...$(NC)"
$(PY) $(SCRIPTS_DIR)/expand-shell-outputs.py --preserve-paths \
  --output-dir $(1)/expanded --cwd .. --format $(2) $(foreach file,$(6),../docs/$(file))
printf '%b\n' "$(DARKYELLOW)  - Concatenating markdown sources...$(NC)"
$(AWK_JOIN) $(foreach file,$(6),$(1)/expanded/docs/$(file)) > $(1)/book.md
$(call NORMALISE_ASSETS,$(1)/book.md)
printf '%b\n' "$(DARKYELLOW)  - Converting markdown to LaTeX...$(NC)"
PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
MERMAID_FILTER_LOC="$(1)/expanded/.mermaid-img" \
  pandoc --from=markdown --to=latex --top-level-division=chapter \
    --syntax-highlighting=none --filter "$(MERMAID_FILTER)" $(LUA_FLAGS) \
    --metadata paper_format=$(2) $(1)/book.md -o $(1)/body.tex
sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $(1)/body.tex
rm -f $(1)/body.tex.bak
awk -f $(BUILD_ASSETS)/latex-table-rules.awk $(1)/body.tex > $(1)/body.tmp
mv $(1)/body.tmp $(1)/body.tex
sed -e 's/@@VERSION@@/v$(VERSION)/g' \
  -e 's/@@BOOK_TITLE@@/$(call shq,$($(4)_TITLE))/g' \
  -e 's/@@BOOK_SUBTITLE@@/$(call shq,$($(4)_SUBTITLE))/g' \
  -e 's/@@COVER@@/$($(4)_COVER)/g' $(3) \
| awk -v body="$(1)/body.tex" \
  '/%%__BOOK_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } { print } END { if (!inserted) exit 2 }' \
  > $(1)/report.tex
$(call RUN_LATEX,$(1),$(5))
cp $(1)/report.pdf $(5)
printf '%b\n' "$(GREEN)OK Document PDF: $(BRIGHTCYAN)\"$(notdir $(5))\"$(GREEN)$(NC)"
endef


define RENDER_EPUB
printf '%b\n' "$(DARKYELLOW)- Building $(BRIGHTCYAN)\"$(notdir $(3))\"$(DARKYELLOW) via EPUB3 pipeline...$(NC)"
rm -rf $(1) && mkdir -p $(1)/expanded/.mermaid-img
ln -sfn $(abspath $(ASSETS_DIR)) $(1)/assets
printf '%b\n' "$(DARKYELLOW)  - Expanding shell command outputs...$(NC)"
$(PY) $(SCRIPTS_DIR)/expand-shell-outputs.py --preserve-paths \
  --output-dir $(1)/expanded --cwd .. --format a4 $(foreach file,$(4),../docs/$(file))
printf '%b\n' "$(DARKYELLOW)  - Concatenating markdown sources...$(NC)"
$(AWK_JOIN) $(foreach file,$(4),$(1)/expanded/docs/$(file)) > $(1)/book.md
$(call NORMALISE_ASSETS,$(1)/book.md)
sed -e 's/@@EPUB_FIGURE_MAX_WIDTH@@/$(EPUB_FIGURE_MAX_WIDTH)/g' \
  $(BUILD_ASSETS)/epub.css.in > $(1)/epub.css
PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
MERMAID_FILTER_FORMAT=svg MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
MERMAID_FILTER_LOC="$(1)/expanded/.mermaid-img" \
  pandoc --from=markdown-raw_html --to=epub3 --mathml \
    --syntax-highlighting=none --toc --toc-depth=2 --css $(1)/epub.css \
    --resource-path=$(1) \
    --epub-cover-image=$($(2)_COVER_PNG) \
    --metadata title="EduMatcher $($(2)_TITLE) (v$(VERSION))" \
    --metadata author="J. Persson, 2026 v$(VERSION)" --metadata lang=en-US \
    --filter "$(MERMAID_FILTER)" $(LUA_FLAGS) $(1)/book.md -o $(3)
  printf '%b\n' "$(DARKYELLOW)  - Running EPUB accessibility checks...$(NC)"
$(PY) $(BUILD_ASSETS)/epub_a11y.py $(3)
  printf '%b\n' "$(GREEN)OK EPUB: $(BRIGHTCYAN)\"$(notdir $(3))\"$(GREEN)$(NC)"
endef


define BOOK_VARS
$(1)_DIR := $(BOOKS_DIR)/$(1)
$(1)_MANIFEST := $$($(1)_DIR)/book.toml
$(1)_REL_SOURCES := $$(shell $(PY) $(BUILD_ASSETS)/book_sources.py --manifest $$($(1)_MANIFEST))
$(1)_SOURCES := $$($(1)_REL_SOURCES)
$(1)_TITLE := $$(shell $(PY) $(BUILD_ASSETS)/book_sources.py --manifest $$($(1)_MANIFEST) --meta title)
$(1)_SUBTITLE := $$(shell $(PY) $(BUILD_ASSETS)/book_sources.py --manifest $$($(1)_MANIFEST) --meta subtitle)
$(1)_COVER := cover-$(1).png
$(1)_COVER_TITLE := $$(COVER_TITLE_$(1))
$(1)_COVER_PLAIN_TITLE := $$($(1)_TITLE)
$(1)_COVER_PNG := $(ASSETS_DIR)/cover-$(1).png
$(1)_EPUB := $(DIST_DIR)/$(PROJECT)_$$(subst -,_,$(1))-$(VERSION).epub
$(1)_EPUB_DL := $(DOWNLOADS_DIR)/$(PROJECT)_$$(subst -,_,$(1)).epub
$(1)_ALL := $(DIST_DIR)/$(PROJECT)_$$(subst -,_,$(1))_all-$(VERSION).zip
$(1)_CHAPTERS := $$(filter-out %/00-part.md %/00-part-2.md %/00-part-3.md %/00-part-4.md %/00-part-5.md,$$($(1)_SOURCES))
$(1)_CH_ZIP := $(DIST_DIR)/$(PROJECT)_$$(subst -,_,$(1))_chapters_a4_bundle-$(VERSION).zip
endef


define PDF_RULE
$(1)_$(2)_PDF := $(DIST_DIR)/$(PROJECT)_$$(subst -,_,$(1))_$$(subst _,_,$(2))-$(VERSION).pdf
$(1)_PDFS += $$($(1)_$(2)_PDF)
$$($(1)_$(2)_PDF): $$($(1)_SOURCES) $$($(1)_MANIFEST) $$($(1)_COVER_PNG) \
    $(BUILD_ASSETS)/templates/$(2).tex.in $(BUILD_ASSETS)/latex-tables.tex \
    $(BUILD_ASSETS)/latex-table-rules.awk $(LUA_DEPS) | $(DIST_DIR)
	@$$(call RENDER_PDF,$(BUILD_DIR)/$(1)/$(2),$(if $(findstring b5,$(2)),b5,a4),$(BUILD_ASSETS)/templates/$(2).tex.in,$(1),$$@,$$($(1)_SOURCES))
endef


define CHAPTER_RULE
$(1)_CHAPTER_PDFS += $(DIST_DIR)/chapters-a4/$(1)/$(basename $(notdir $(2))).pdf
$(DIST_DIR)/chapters-a4/$(1)/$(basename $(notdir $(2))).pdf: $(2) $$($(1)_COVER_PNG) $(BUILD_ASSETS)/templates/a4.tex.in \
    $(BUILD_ASSETS)/latex-tables.tex $(BUILD_ASSETS)/latex-table-rules.awk $(LUA_DEPS)
	@mkdir -p $$(@D)
	@$$(call RENDER_PDF,$(BUILD_DIR)/$(1)/chapters/$(basename $(notdir $(2))),a4,$(BUILD_ASSETS)/templates/a4.tex.in,$(1),$$@,$(2))
endef


define BOOK_TARGETS
$$($(1)_COVER_PNG): $(ASSETS_DIR)/cover-$(1)-template.html $(STAMP_DIR)/version-$(VERSION)
	@printf '%b\n' "$(DARKYELLOW)- Building cover image for $(BRIGHTCYAN)$(1)$(DARKYELLOW)...$(NC)"
	@sed -e 's/@@VERSION@@/v$(VERSION)/g' \
      -e 's|@@COVER_PLAIN_TITLE@@|$$(call shq,$$($(1)_COVER_PLAIN_TITLE))|g' \
      -e 's|@@COVER_TITLE@@|$$(call shq,$$($(1)_COVER_TITLE))|g' \
      $$< > $(ASSETS_DIR)/cover-$(1).html
	@$(SCRIPTS_DIR)/mkfigs.sh -o $(ASSETS_DIR) -s $(ASSETS_DIR) cover-$(1)
	@printf '%b\n' "$(GREEN)OK cover image: $(BRIGHTCYAN)cover-$(1).png$(GREEN)$(NC)"

$$($(1)_EPUB): $$($(1)_SOURCES) $$($(1)_MANIFEST) $$($(1)_COVER_PNG) $(BUILD_ASSETS)/epub.css.in $(BUILD_ASSETS)/epub_a11y.py
	@$$(call RENDER_EPUB,$(BUILD_DIR)/$(1)/epub,$(1),$$@,$$($(1)_SOURCES))

# Unversioned copy under the site's docs tree, so the download link in
# index.md never needs updating on a version bump.
$$($(1)_EPUB_DL): $$($(1)_EPUB) | $(DOWNLOADS_DIR)
	@cp $$< $$@
	@printf '%b\n' "$(GREEN)OK EPUB download: $(BRIGHTCYAN)$$(notdir $$@)$(GREEN)$(NC)"

$$($(1)_CH_ZIP): $$($(1)_CHAPTER_PDFS)
	@printf '%b\n' "$(DARKYELLOW)- Bundling chapter PDFs for $(BRIGHTCYAN)$(1)$(DARKYELLOW)...$(NC)" && zip -9 -j -q $$@ $$^ && printf '%b\n' "$(GREEN)OK chapter bundle: $(BRIGHTCYAN)$(PROJECT)_$(subst -,_,$(1))_chapters_a4_bundle-$(VERSION).zip$(GREEN)$(NC)"

.PHONY: pdf-$(1) epub-$(1) chapters-$(1) cover-$(1) book-$(1) epub-verify-$(1) epub-download-$(1)
pdf-$(1): check-latex-engine $$($(1)_ALL)
epub-$(1): $$($(1)_EPUB)
epub-download-$(1): $$($(1)_EPUB_DL)
chapters-$(1): check-latex-engine $$($(1)_CHAPTER_PDFS) $$($(1)_CH_ZIP)
cover-$(1): $$($(1)_COVER_PNG)
book-$(1): pdf-$(1) epub-$(1)
epub-verify-$(1): $$($(1)_EPUB)
	@command -v epubcheck >/dev/null || { echo 'epubcheck not found' >&2; exit 1; }
	@epubcheck $$<
endef

$(foreach book,$(BOOKS),$(eval $(call BOOK_VARS,$(book))))
$(foreach book,$(BOOKS),$(foreach variant,$(VARIANTS),$(eval $(call PDF_RULE,$(book),$(variant)))))
$(foreach book,$(BOOKS),$(foreach chapter,$($(book)_CHAPTERS),$(eval $(call CHAPTER_RULE,$(book),$(chapter)))))
$(foreach book,$(BOOKS),$(eval $(call BOOK_TARGETS,$(book))))

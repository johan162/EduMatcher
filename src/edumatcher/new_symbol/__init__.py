"""
pm-new-symbol (alias pm-ipo) — list a new symbol in an engine configuration.

Listing a symbol is the exchange's side of an IPO: the book is created with a
reference price (the offer price) and, where the venue has market makers, an
opening seed quote. A mistake in either is visible from the first order, so
this command refuses rather than guesses:

  * It edits the file the running exchange was built from (the deployed
    artifact's ``meta.source_path``) unless ``--config`` names another, and
    redeploys only that file. The ``ref_data/`` copy is never edited on its
    own: the authored source would lose the symbol on its next deploy.
  * It refuses to deploy while ``pm-engine`` runs, while the source has edits
    that were never deployed, and while the data directory still holds saved
    state for the symbol, which the engine would restore in place of the IPO
    price.
  * The edited file is validated as a whole before anything is written, and
    the edit is checked to have changed nothing but the new symbol.

Modules
-------
``main``       command line: parser, entry point and output
``config``     which configuration file is edited, and whether it is deployed
``guards``     exchange state that must not be present: a running engine,
               saved state for the symbol
``listing``    the new symbol's entry: IPO price, seed quote, optional sections
``yaml_edit``  appending that entry to the YAML text without disturbing it
``install``    the whole sequence: check, edit, validate, write, deploy
"""

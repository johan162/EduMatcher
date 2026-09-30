"""The valuation model: pure functions from frozen inputs to frozen results.

Nothing here reads files, the clock or the environment, so every result is
reproducible and checkable against the worked example in
docs-design/EduMatcher-valuation.md §18.

``forecast``  §6  operating forecast: customers, staff, costs, tax, FCFF
``rates``     §7  discount rate for each DCF stage
``dcf``       §8  two-stage DCF and terminal value
``bridge``    §9  enterprise value to value per share, capitalisation, dilution
``comps``     §10 comparables cross-check and the fair-value blend
``valuation`` resolved answers in, the whole deterministic valuation out
``offering``  §13–§16 range, management floor, book-building, allocation, pop
``index_rules`` §17 the fictive index rulebook
``scenarios`` §11 bear/base/bull, tornado, sensitivity grids
``montecarlo`` §12 correlated draws of the scenario drivers
``checks``    §24 the warnings catalogue
"""

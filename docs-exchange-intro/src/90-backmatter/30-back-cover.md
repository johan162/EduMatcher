
# Back-Cover Text

You can write production-grade software in many domains without ever asking what a "spread" really is, why a matching engine must be deterministic, or what happens when a market suddenly halts.

Financial exchanges are not one of those domains.

*How a Financial Exchange Works* is a practical conceptual guide for developers, architects, product owners, QA engineers, and operations teams who need to understand market structure fast, without wading through rulebooks before they can ship. It explains the language, mechanics, and failure modes of modern markets in plain English: from bids, asks, and order books to auctions, implied matching, risk controls, clearing, settlement, surveillance, and market data economics.

This second edition is significantly expanded and updated, with deeper treatment of exchange microstructure, implementation-relevant architecture, and the real operational realities teams face in live systems.

Inside you will learn:

- How exchanges create price discovery, liquidity, and fairness
- How orders, priority rules, and matching logic produce trades
- Why tick sizes, auctions, and market fragmentation matter in practice
- How risk controls, conformance testing, and post-trade processes keep markets stable
- Where real-world edge cases appear, and what they imply for system design

No hype. No hand-waving. No prerequisite finance degree.

Just the map you need to stop translating jargon and start reasoning clearly about the system you are building.

# About the Author

Johan Persson is a software engineer and musician with over 30 years of experience in high-performance, safety-critical systems. He has worked in multiple fields in software design and among them modern financial trading systems, as well as with thruster design for satellite control systems. Johan is passionate about making complex systems understandable and accessible and actually enjoys writing documentation. Johan lives in Sweden with his family and enjoys playing banjo (5-string, of-course!), cycling, wood-working, and when time allows, doing electronics design for analog computers.

As a companion to this book Johan has also written an educational exchange platform `EduMatcher` which implements many of the techniques discussed in this book. While out of necessity it is simplified compared with real exchanges it is still a surprisingly complete multi-process, message-bus based trading platform that can run on a laptop. It uses its own protocol suit with names that is a wink to the fintech industry; ALF, BALF, CALF, RALF, and LALF, with ALF=**AL**most **F**ix, BALF=**B**inary **ALF**, CALF=**C**hannel **ALF**, RALF=**R**econcilliation **ALF**, LALF=**L**ogging **ALF**.  It makes an excellent companion to run while reading this book!
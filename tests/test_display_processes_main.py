from __future__ import annotations

import logging

from edumatcher.board import main as board_main
from edumatcher.ticker import main as ticker_main
from edumatcher.viewer import main as viewer_main


class TestTickerMain:
    def test_build_parser_logging_flags(self) -> None:
        parser = ticker_main._build_parser()
        args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"

    def test_configure_logging_default_warning(self) -> None:
        parser = ticker_main._build_parser()
        args = parser.parse_args([])
        assert ticker_main._configure_logging(args) == logging.WARNING


class TestBoardMain:
    def test_build_parser_logging_flags(self) -> None:
        parser = board_main._build_parser()
        args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"

    def test_configure_logging_default_warning(self) -> None:
        parser = board_main._build_parser()
        args = parser.parse_args([])
        assert board_main._configure_logging(args) == logging.WARNING


class TestViewerMain:
    def test_build_parser_logging_flags(self) -> None:
        parser = viewer_main._build_parser()
        args = parser.parse_args(
            ["--symbol", "AAPL", "-vv", "--quiet", "--log-level", "ERROR"]
        )
        assert args.symbol == "AAPL"
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"

    def test_configure_logging_default_warning(self) -> None:
        parser = viewer_main._build_parser()
        args = parser.parse_args(["--symbol", "AAPL"])
        assert viewer_main._configure_logging(args) == logging.WARNING

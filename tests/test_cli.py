from __future__ import annotations

from buscador.cli import build_parser


def test_run_accepts_render_flag():
    args = build_parser().parse_args(["run", "--render"])

    assert args.render is True


def test_run_renders_by_default():
    args = build_parser().parse_args(["run"])

    assert args.render is True


def test_run_accepts_no_render():
    args = build_parser().parse_args(["run", "--no-render"])

    assert args.render is False

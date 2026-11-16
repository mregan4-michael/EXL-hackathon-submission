from factory.cli import main


def test_cli_returns_zero_without_args() -> None:
    assert main([]) == 0

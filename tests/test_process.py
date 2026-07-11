from agent_reach.utils.process import (
    bundled_mcporter_config_path,
    mcporter_cli_prefix,
    mcporter_utf8_env_args,
    utf8_subprocess_env,
)


def test_utf8_subprocess_env_forces_python_utf8():
    env = utf8_subprocess_env({"PYTHONUTF8": "0", "OTHER": "value"})

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["OTHER"] == "value"


def test_mcporter_utf8_env_args():
    assert mcporter_utf8_env_args() == [
        "--env",
        "PYTHONUTF8=1",
        "--env",
        "PYTHONIOENCODING=utf-8",
    ]


def test_bundled_mcporter_config_path_finds_repo_config():
    path = bundled_mcporter_config_path()
    assert path is not None
    assert path.name == "mcporter.json"


def test_mcporter_cli_prefix_includes_config():
    prefix = mcporter_cli_prefix()
    assert prefix[0] == "mcporter"
    if bundled_mcporter_config_path() is not None:
        assert "--config" in prefix

"""The initial gallery user is created with hidden local password input."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from pydantic import SecretStr
from sqlalchemy import select

from drone_media_manager.auth.passwords import verify_password
from drone_media_manager.cli.server import alembic_config, main
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def test_create_user_reads_password_twice_without_printing_it(
    tmp_path: Path, capsys: object
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "users.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    prompts: list[str] = []
    answers = iter(["secret password 🔒", "secret password 🔒"])

    def hidden_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    result = main(
        ["user", "create", "--username", "Editor"],
        settings_loader=lambda: settings,
        password_reader=hidden_input,
    )
    assert result == 0
    assert len(prompts) == 2
    assert "secret password" not in capsys.readouterr().out  # type: ignore[attr-defined]
    engine = create_engine_from_settings(settings)
    with session_factory(engine)() as session:
        user = session.scalar(select(User).where(User.username == "editor"))
        assert user is not None
        assert verify_password("secret password 🔒", user.password_hash)
    engine.dispose()

"""The real salary lives in .env, not in config.yaml.

config.yaml is published in the repo, so its figures are an example. These
tests pin down that .env wins, that an empty value overrides nothing, and that
a malformed value does not take the bot down.
"""

from __future__ import annotations

from jobbot.container import Container
from jobbot.settings import Settings


def _settings(tmp_path, **extra) -> Settings:
    config = tmp_path / "config.yaml"
    config.write_text("salary:\n  minimum: 30000\n  target: 45000\n", encoding="utf-8")
    profile = tmp_path / "cv.yaml"
    profile.write_text("name: Quien Sea\n", encoding="utf-8")
    campos = dict(
        telegram_bot_token=None,
        telegram_chat_id=None,
        anthropic_api_key=None,
        db_path=tmp_path / "jobs.sqlite3",
        config_path=config,
        profile_path=profile,
        log_level="WARNING",
        source_cookies={},
        cookie_path=tmp_path / "cookies.json",
        browser_profile_path=tmp_path / "browser",
        source_credentials={},
        salary_minimum=None,
        salary_target=None,
    )
    campos.update(extra)
    return Settings(**campos)


def test_sin_variables_manda_el_yaml(tmp_path) -> None:
    criteria = Container(_settings(tmp_path)).criteria
    assert (criteria.salary.minimum, criteria.salary.target) == (30000, 45000)


def test_el_entorno_pisa_al_yaml(tmp_path) -> None:
    settings = _settings(tmp_path, salary_minimum=35000, salary_target=50000)
    criteria = Container(settings).criteria
    assert (criteria.salary.minimum, criteria.salary.target) == (35000, 50000)


def test_se_puede_pisar_solo_una_de_las_dos(tmp_path) -> None:
    criteria = Container(_settings(tmp_path, salary_minimum=35000)).criteria
    assert (criteria.salary.minimum, criteria.salary.target) == (35000, 45000)


def test_recargar_la_config_no_pierde_lo_del_entorno(tmp_path) -> None:
    """The bot re-reads config.yaml on every search; if that wiped the value
    from .env, the salary would silently fall back to the example one."""
    settings = _settings(tmp_path, salary_minimum=35000)
    container = Container(settings)
    settings.config_path.write_text(
        "salary:\n  minimum: 30000\n  target: 48000\n", encoding="utf-8"
    )
    assert container.reload_criteria() is True
    assert container.criteria.salary.minimum == 35000
    assert container.criteria.salary.target == 48000


def test_un_valor_mal_escrito_se_ignora(monkeypatch) -> None:
    monkeypatch.setenv("JOBBOT_SALARY_MINIMUM", "cuarenta mil")
    monkeypatch.setenv("JOBBOT_SALARY_TARGET", "")
    settings = Settings.from_env()
    assert settings.salary_minimum is None
    assert settings.salary_target is None

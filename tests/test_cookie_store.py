from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jobbot.adapters.cookie_store import CookieStore


def test_guarda_y_recupera(tmp_path) -> None:
    store = CookieStore(tmp_path / "cookies.json")
    store.save("infojobs", "sid=abc", datetime.now(UTC) + timedelta(days=30))

    loaded = store.load()["infojobs"]
    assert loaded.value == "sid=abc"
    assert loaded.is_expired is False


def test_una_cookie_caducada_no_se_usa(tmp_path) -> None:
    store = CookieStore(tmp_path / "cookies.json")
    store.save("glassdoor", "sid=viejo", datetime.now(UTC) - timedelta(days=1))
    store.save("infojobs", "sid=nuevo", datetime.now(UTC) + timedelta(days=10))

    # load() returns them all so they can be reported; usable() only live ones.
    assert set(store.load()) == {"glassdoor", "infojobs"}
    assert store.usable() == {"infojobs": "sid=nuevo"}


def test_guardar_una_no_pisa_las_demas(tmp_path) -> None:
    store = CookieStore(tmp_path / "cookies.json")
    store.save("infojobs", "sid=uno", None)
    store.save("glassdoor", "sid=dos", None)

    assert set(store.load()) == {"infojobs", "glassdoor"}


def test_renovar_reemplaza_el_valor(tmp_path) -> None:
    store = CookieStore(tmp_path / "cookies.json")
    store.save("infojobs", "sid=viejo", None)
    store.save("infojobs", "sid=nuevo", None)

    assert store.load()["infojobs"].value == "sid=nuevo"


def test_describe_nunca_filtra_la_cookie(tmp_path) -> None:
    """describe() is what `jobbot cookies` prints to the screen."""
    store = CookieStore(tmp_path / "cookies.json")
    cookie = store.save("infojobs", "sid=secretisimo", datetime.now(UTC) + timedelta(days=5))

    assert "secretisimo" not in cookie.describe()
    assert "valida" in cookie.describe()


def test_fichero_corrupto_no_revienta(tmp_path) -> None:
    path = tmp_path / "cookies.json"
    path.write_text("{esto no es json", encoding="utf-8")

    assert CookieStore(path).load() == {}


def test_sin_fichero_devuelve_vacio(tmp_path) -> None:
    assert CookieStore(tmp_path / "no-existe.json").load() == {}


def test_borrar_una_sesion(tmp_path) -> None:
    store = CookieStore(tmp_path / "cookies.json")
    store.save("infojobs", "sid=abc", None)

    assert store.delete("infojobs") is True
    assert store.delete("infojobs") is False
    assert store.load() == {}

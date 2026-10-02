from odd.db import LUGARES_PLACA
from odd.handlers import (
    CODE_ALPHABET,
    SOLO_NUMERO_RE,
    generate_code,
    normalize_code,
    sanitize,
)
from odd.lexicon import LUGAR_PLACA, LUGAR_PLACA_BUTTONS


def test_los_codigos_generados_se_leen_bien():
    for _ in range(200):
        code = generate_code()
        assert normalize_code(code) == code
        assert not (set(code) - set(CODE_ALPHABET + "ODD-"))


def test_reconoce_el_codigo_aunque_venga_sucio():
    """El dueño del bar lo va a copiar y pegar con lo que venga alrededor."""
    assert normalize_code("odd-ab12-cd34") == "ODD-AB12-CD34"
    assert normalize_code("hola! me dieron este ODD AB12 CD34 gracias") == "ODD-AB12-CD34"
    assert normalize_code("ODDAB12CD34") == "ODD-AB12-CD34"


def test_texto_que_no_es_codigo():
    assert normalize_code("hola") is None
    assert normalize_code("") is None
    assert normalize_code("ODD-AB12") is None


def test_un_mensaje_que_es_solo_un_numero_es_una_placa():
    assert SOLO_NUMERO_RE.match("47").group(1) == "47"
    assert SOLO_NUMERO_RE.match(" #47 ").group(1) == "47"
    assert SOLO_NUMERO_RE.match("placa 47") is None
    assert SOLO_NUMERO_RE.match("1234567") is None


def test_sanitize_saca_lo_que_rompe_el_formato():
    assert sanitize("el *bar* de _la esquina_", 40) == "el bar de la esquina"
    assert sanitize("mira   esto\n\notro", 40) == "mira esto otro"
    assert sanitize("a" * 200, 40) == "a" * 40
    assert sanitize("", 40) == ""


def test_los_botones_de_la_placa_mapean_a_lugares_reales():
    assert set(LUGAR_PLACA_BUTTONS.values()) <= set(LUGARES_PLACA)
    assert set(LUGAR_PLACA) == set(LUGARES_PLACA)

from glitchmap.handlers import (
    CODE_ALPHABET,
    generate_code,
    normalize_code,
    sanitize,
)
from glitchmap.lexicon import COBERTURA, COBERTURA_BUTTONS, INTERFERENCIA_BUTTONS, VENTANA_BUTTONS


def test_los_codigos_generados_se_leen_bien():
    for _ in range(200):
        code = generate_code()
        assert normalize_code(code) == code
        assert not (set(code) - set(CODE_ALPHABET + "GLX-"))


def test_reconoce_el_codigo_aunque_venga_sucio():
    assert normalize_code("glx-ab12-cd34") == "GLX-AB12-CD34"
    assert normalize_code("hola, mi codigo es GLX AB12 CD34 gracias") == "GLX-AB12-CD34"
    assert normalize_code("GLXAB12CD34") == "GLX-AB12-CD34"


def test_texto_que_no_es_codigo():
    assert normalize_code("hola") is None
    assert normalize_code("") is None
    assert normalize_code("GLX-AB12") is None


def test_sanitize_saca_lo_que_rompe_el_formato():
    assert sanitize("el *banco* del _fondo_", 40) == "el banco del fondo"
    assert sanitize("mira   esto\n\notro", 40) == "mira esto otro"
    assert sanitize("a" * 100, 40) == "a" * 40
    assert sanitize("", 40) == ""


def test_las_etiquetas_de_los_botones_mapean_a_claves_conocidas():
    assert set(COBERTURA_BUTTONS.values()) == set(COBERTURA)
    assert len(set(INTERFERENCIA_BUTTONS.values())) == len(INTERFERENCIA_BUTTONS)
    assert len(set(VENTANA_BUTTONS.values())) == len(VENTANA_BUTTONS)

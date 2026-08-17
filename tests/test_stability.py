from datetime import datetime, timedelta, timezone

from glitchmap.stability import BASE_SCORE, COLLAPSE, CONFIRM, is_faded, label, stability

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


def test_glitch_nuevo_arranca_en_la_base():
    assert stability(days_ago(0), [], NOW) == int(BASE_SCORE)


def test_confirmar_sube_y_colapsar_baja():
    solo = stability(days_ago(1), [], NOW)
    con_confirmacion = stability(days_ago(1), [(CONFIRM, days_ago(0))], NOW)
    con_colapso = stability(days_ago(1), [(COLLAPSE, days_ago(0))], NOW)
    assert con_confirmacion > solo > con_colapso


def test_tres_colapsos_frescos_lo_desvanecen():
    signals = [(COLLAPSE, days_ago(i)) for i in (0, 1, 2)]
    score = stability(days_ago(10), signals, NOW)
    assert is_faded(score)
    assert label(score) == "DESVANECIDO"


def test_las_confirmaciones_viejas_pesan_menos():
    fresca = stability(days_ago(100), [(CONFIRM, days_ago(0))], NOW)
    vieja = stability(days_ago(100), [(CONFIRM, days_ago(90))], NOW)
    assert fresca > vieja


def test_el_silencio_erosiona_pero_no_antes_de_la_gracia():
    reciente = stability(days_ago(40), [], NOW)
    olvidado = stability(days_ago(300), [], NOW)
    assert reciente == int(BASE_SCORE)
    assert olvidado < reciente


def test_un_lugar_confirmado_seguido_se_mantiene_estable():
    signals = [(CONFIRM, days_ago(i)) for i in (1, 5, 12, 20)]
    assert label(stability(days_ago(60), signals, NOW)) == "ESTABLE"


def test_score_siempre_entre_0_y_100():
    muchos_confirms = [(CONFIRM, days_ago(0))] * 50
    muchos_colapsos = [(COLLAPSE, days_ago(0))] * 50
    assert stability(days_ago(1), muchos_confirms, NOW) == 100
    assert stability(days_ago(1), muchos_colapsos, NOW) == 0

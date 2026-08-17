from glitchmap.geo import bounding_box, format_distance, haversine_m


def test_distancia_conocida_obelisco_a_congreso():
    # Obelisco -> Congreso, Buenos Aires: ~1,6 km segun cualquier mapa.
    metros = haversine_m(-34.603722, -58.381592, -34.609722, -58.392500)
    assert 1100 < metros < 1300


def test_distancia_cero():
    assert haversine_m(-34.6, -58.4, -34.6, -58.4) == 0.0


def test_bounding_box_contiene_al_circulo():
    lat, lon, radio = -34.6, -58.4, 3000
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radio)
    assert min_lat < lat < max_lat
    assert min_lon < lon < max_lon
    # Un punto justo en el borde del radio tiene que caer dentro de la caja.
    borde = lat + (max_lat - lat) * 0.99
    assert min_lat <= borde <= max_lat


def test_bounding_box_cerca_del_polo_no_explota():
    min_lat, max_lat, min_lon, max_lon = bounding_box(90.0, 0.0, 5000)
    assert min_lon == -180.0 and max_lon == 180.0
    assert max_lat <= 90.0


def test_formato_de_distancia():
    assert format_distance(120) == "120 m"
    assert format_distance(1500) == "1,5 km"

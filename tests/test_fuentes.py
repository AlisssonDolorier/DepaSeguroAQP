"""Pruebas de lectura de fuentes con respuestas simuladas: no dependen de internet."""
import json

import pandas as pd
import pytest
import requests

from depaseguro.dao.repositorios import FuenteDAO, IndicadorDAO
from depaseguro.ingestion.fuentes import (FuenteBCRP, FuenteCiberdelitos, FuenteDenuncias, FuenteOpenStreetMap,
                                          FuenteSunedu, FuenteTransparencia, FuenteWikidata, decodificar)
from depaseguro.ingestion.planificador import ejecutar_ingesta
from .conftest import crear_aviso, crear_usuario


class Respuesta:
    def __init__(self, contenido, estado=200):
        self.status_code = estado
        self.content = contenido if isinstance(contenido, bytes) else str(contenido).encode()
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class SesionFalsa:
    """Responde según un fragmento de la URL, igual que un servidor real."""

    def __init__(self, rutas):
        self.rutas = rutas
        self.headers = {}
        self.llamadas = []

    def get(self, url, **_opciones):
        self.llamadas.append(url)
        for fragmento, respuesta in self.rutas.items():
            if fragmento in url:
                if isinstance(respuesta, Exception):
                    raise respuesta
                return respuesta
        return Respuesta("{}", 404)


BCRP_TC = json.dumps({"periods": [{"name": "03.Nov.26", "values": ["3.450"]}, {"name": "04.Nov.26", "values": ["n.d."]}]})
BCRP_IPC = json.dumps({"periods": [{"name": "Oct.2026", "values": ["120.5"]}]})


def sesion_bcrp():
    return SesionFalsa({"PD04640PD": Respuesta(BCRP_TC), "PN38705PM": Respuesta(BCRP_IPC)})


def test_bcrp_guarda_y_omite_vacios(db):
    resultado = FuenteBCRP(db, sesion_bcrp()).ejecutar()
    assert resultado["estado"] == "ok" and resultado["registros"] == 2
    indicadores = IndicadorDAO(db)
    assert indicadores.ultimo("tipo_cambio_venta") == {
        "clave": "tipo_cambio_venta", "periodo": "2026-11-03", "valor": 3.45, "fuente": "bcrp"}
    assert indicadores.ultimo("ipc_lima")["periodo"] == "2026-10"


def test_fuente_sin_cambios_no_recarga(db):
    FuenteBCRP(db, sesion_bcrp()).ejecutar()
    assert FuenteBCRP(db, sesion_bcrp()).ejecutar()["estado"] == "sin_cambios"


def test_error_de_red_se_registra_y_conserva_datos(db):
    FuenteBCRP(db, sesion_bcrp()).ejecutar()
    fallida = SesionFalsa({"PD04640PD": requests.ConnectionError("sin red")})
    resultado = FuenteBCRP(db, fallida).ejecutar()
    assert resultado["estado"] == "error"
    assert IndicadorDAO(db).ultimo("tipo_cambio_venta")["valor"] == 3.45
    fuente = FuenteDAO(db).obtener("bcrp")
    assert fuente["estado"] == "error" and fuente["ultimo_exito"] is not None


def test_error_http_no_detiene_lectura(db):
    resultado = FuenteBCRP(db, SesionFalsa({"PD04640PD": Respuesta("caido", 503)})).ejecutar()
    assert resultado["estado"] == "error" and "503" in resultado["mensaje"]


def test_denuncias_descubre_archivo_y_filtra_arequipa(db):
    catalogo = {"result": [{"resources": [
        {"name": "DataSet Denuncias Policiales - Enero 2025", "format": "csv", "url": "https://x/enero.csv"},
        {"name": "DataSet - Denuncias Policiales - Enero 2018 a Septiembre 2026", "format": "csv", "url": "https://x/historico.csv"},
    ]}]}
    csv = ('"ANIO","MES","DPTO_HECHO_NEW","PROV_HECHO","DIST_HECHO","UBIGEO_HECHO","P_MODALIDADES","cantidad"\n'
           '"2026","9","AREQUIPA","AREQUIPA","CAYMA","40103","Estafa",7\n'
           '"2026","9","AREQUIPA","AREQUIPA","CAYMA","40103","Estafa",3\n'
           '"2026","9","AREQUIPA","ISLAY","MOLLENDO","40701","Estafa",4\n'
           '"2026","9","LIMA","LIMA","LIMA","150101","Estafa",99\n')
    sesion = SesionFalsa({"package_show": Respuesta(json.dumps(catalogo)), "historico.csv": Respuesta(csv)})
    resultado = FuenteDenuncias(db, sesion).ejecutar()
    assert resultado["estado"] == "ok"
    fila = db.execute("SELECT * FROM denuncias_distrito").fetchall()
    assert len(fila) == 1 and fila[0]["ubigeo"] == "040103" and fila[0]["cantidad"] == 10


def test_denuncias_actualiza_csv_en_la_misma_url_y_preserva_el_ultimo_valido(db):
    catalogo = {"result": {"resources": [
        {"name": "Denuncias de Enero 2018 a Septiembre 2026", "format": "CSV", "url": "https://x/historico.csv"}
    ]}}
    cabecera = "ANIO,MES,DIST_HECHO,UBIGEO_HECHO,P_MODALIDADES,cantidad\n"
    sesion = SesionFalsa({"package_show": Respuesta(json.dumps(catalogo)),
                          "historico.csv": Respuesta(cabecera + "2026,9,CAYMA,040103,Estafa,7\n")})
    fuente = FuenteDenuncias(db, sesion)
    assert fuente.ejecutar()["estado"] == "ok"
    assert fuente.ejecutar()["estado"] == "sin_cambios"
    sesion.rutas["historico.csv"] = Respuesta(cabecera + "2026,9,CAYMA,040103,Estafa,9\n")
    assert fuente.ejecutar()["estado"] == "ok"
    sesion.rutas["historico.csv"] = Respuesta(cabecera)
    assert fuente.ejecutar()["estado"] == "error"
    assert db.execute("SELECT cantidad FROM denuncias_distrito").fetchone()[0] == 9


def test_denuncias_importa_archivos_anuales_del_portal(db):
    catalogo = {"result": {"resources": [
        {"name": f"DataSet - Denuncias Policiales - {anio}", "format": "csv", "url": f"https://x/{anio}.csv"}
        for anio in (2025, 2026)
    ]}}
    cabecera = "ANIO_REGISTRO,MES_REGISTRO,DIST_HECHO,UBIGEO_HECHO,P_MODALIDADES,cantidad\n"
    sesion = SesionFalsa({"package_show": Respuesta(json.dumps(catalogo)),
                          "2025.csv": Respuesta(cabecera + "2025,2,CAYMA,040103,Estafa,7\n"),
                          "2026.csv": Respuesta(cabecera + "2026,3,CAYMA,040103,Estafa,9\n")})
    fuente = FuenteDenuncias(db, sesion)
    assert fuente.ejecutar()["registros"] == 2
    filas = db.execute("SELECT anio, mes, cantidad FROM denuncias_distrito ORDER BY anio")
    assert [tuple(fila) for fila in filas] == [(2025, 2, 7), (2026, 3, 9)]
    sesion.rutas["2026.csv"] = Respuesta(cabecera + "2026,4,CAYMA,040103,Estafa,12\n")
    assert fuente.ejecutar()["estado"] == "ok"
    filas = db.execute("SELECT anio, mes, cantidad FROM denuncias_distrito ORDER BY anio")
    assert [tuple(fila) for fila in filas] == [(2025, 2, 7), (2026, 4, 12)]


def test_denuncias_falla_si_cambia_el_catalogo(db):
    catalogo = {"result": [{"resources": [{"name": "Otro", "format": "csv", "url": "https://x/o.csv"}]}]}
    resultado = FuenteDenuncias(db, SesionFalsa({"package_show": Respuesta(json.dumps(catalogo))})).ejecutar()
    assert resultado["estado"] == "error"


def test_ciberdelitos_acumula_varios_archivos(db):
    fuente = FuenteCiberdelitos(db, SesionFalsa({}))
    tabla = pd.DataFrame({"distrito_fiscal": ["AREQUIPA", "AREQUIPA", "LIMA", "AREQUIPA"], "anio_denuncia": ["2026"] * 4,
                          "generico": ["LEY 30096"] * 3 + ["CONTRA EL PATRIMONIO"],
                          "des_articulo": ["Fraude informático"] * 3 + ["HURTO"], "cantidad": ["2", "3", "100", "900"]})
    assert fuente.guardar(tabla) == 1
    fuente.guardar(tabla)
    assert db.execute("SELECT cantidad FROM ciberdelitos").fetchone()[0] == 10


def test_sunedu_registra_locales_sin_duplicar(db):
    tabla = pd.DataFrame({
        "NOMBRE": ["U1", "U1", "U2", "U3"], "CODIGO_LOCAL": ["L1", "L1", "L2", "L3"],
        "DEPARTAMENTO_LOCAL": ["AREQUIPA", "AREQUIPA", "LIMA", "AREQUIPA"], "PROVINCIA_LOCAL": ["AREQUIPA", "AREQUIPA", "LIMA", "AREQUIPA"],
        "DISTRITO_LOCAL": ["CAYMA", "CAYMA", "LIMA", "CAYMA"], "LATITUD_UBICACION": ["-16.4", "-16.4", "-12", "x"],
        "LONGITUD_UBICACION": ["-71.5", "-71.5", "-77", "y"], "ESTADO_LICENCIAMIENTO": ["LICENCIA OTORGADA"] * 4,
        "FECHA_CORTE": ["20240828"] * 4})
    assert FuenteSunedu(db, SesionFalsa({})).guardar(tabla) == 1


def test_wikidata_empareja_sin_tildes(db):
    fuente = FuenteWikidata(db, SesionFalsa({}))
    total = fuente.cargar([{"distrito": "Distrito de Sabandía", "poblacion": 9674}, {"distrito": "Arequipa", "poblacion": 1}])
    assert total == 1
    assert db.execute("SELECT poblacion FROM distritos WHERE ubigeo = '040116'").fetchone()[0] == 9674


def test_transparencia_lee_csv(db):
    csv = "Entity,Code,Year,Corruption Perceptions Index,World region according to OWID\nPeru,PER,2024,31,South America\nChile,CHL,2024,63,South America\n"
    resultado = FuenteTransparencia(db, SesionFalsa({"ti-corruption": Respuesta(csv)})).ejecutar()
    assert resultado["registros"] == 1
    assert IndicadorDAO(db).ultimo("cpi_peru")["valor"] == 31


def test_openstreetmap_marca_direccion(db, monkeypatch):
    monkeypatch.setattr("depaseguro.ingestion.fuentes.time.sleep", lambda _s: None)
    dueno = crear_usuario(db, "osm@prueba.test")
    encontrado = crear_aviso(db, dueno, direccion="Calle Real 1", direccion_estado="sin_verificar", lat=None, lon=None)
    perdido = crear_aviso(db, dueno, direccion="No Existe 9", direccion_estado="sin_verificar", lat=None, lon=None)
    lejano = crear_aviso(db, dueno, direccion="Muy Lejos 5", direccion_estado="sin_verificar", lat=None, lon=None)
    sesion = SesionFalsa({
        "Real": Respuesta(json.dumps([{"lat": "-16.40", "lon": "-71.53", "display_name": "Calle Real"}])),
        "No+Existe": Respuesta("[]"), "Lejos": Respuesta(json.dumps([{"lat": "-12.0", "lon": "-77.0", "display_name": "Lima"}]))})
    sesion.get = lambda url, params=None, **_o: _responder_osm(params)
    FuenteOpenStreetMap(db, sesion).ejecutar()
    estado = lambda i: db.execute("SELECT direccion_estado FROM inmuebles WHERE id = ?", (i,)).fetchone()[0]
    assert (estado(encontrado), estado(perdido), estado(lejano)) == ("verificada", "no_encontrada", "fuera_distrito")


def _responder_osm(parametros):
    consulta = parametros["q"]
    if "Real" in consulta:
        return Respuesta(json.dumps([{"lat": "-16.40", "lon": "-71.53", "display_name": "Calle Real"}]))
    if "Lejos" in consulta:
        return Respuesta(json.dumps([{"lat": "-12.0", "lon": "-77.0", "display_name": "Lima"}]))
    return Respuesta("[]")


@pytest.mark.parametrize("contenido,esperado", [("Cañón".encode("utf-8"), "Cañón"), ("Cañón".encode("cp1252"), "Cañón")])
def test_decodificar_ambas_codificaciones(contenido, esperado):
    assert decodificar(contenido) == esperado


def test_ejecucion_completa_tolera_fallas(db, monkeypatch):
    monkeypatch.setattr("requests.Session.get", lambda *_a, **_k: (_ for _ in ()).throw(requests.ConnectionError("sin red")))
    resultados = ejecutar_ingesta(db)
    assert len(resultados) == 7
    assert sum(r["estado"] == "error" for r in resultados) >= 5

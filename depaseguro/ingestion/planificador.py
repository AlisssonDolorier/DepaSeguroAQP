"""Ejecuta la lectura de fuentes de forma manual o programada."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from ..dao.base import conectar
from ..services.alertas import alertas_zona
from ..services.evaluador import reevaluar_todos
from .fuentes import FUENTES, FuenteOpenStreetMap, registrar_catalogo

log = logging.getLogger("depaseguro.ingesta")
_candado = threading.Lock()


def ejecutar_ingesta(conexion, solo: str | None = None, *, geocodificar: bool = True) -> list[dict]:
    """Lee las fuentes, recalcula los avisos y genera alertas de zona."""
    if not _candado.acquire(blocking=False):
        return [{"fuente": "todas", "estado": "ocupado", "registros": 0,
                 "mensaje": "Ya hay una lectura en curso."}]
    try:
        registrar_catalogo(conexion)
        clases = [clase for clase in FUENTES if solo in (None, clase.clave)
                  and (geocodificar or clase is not FuenteOpenStreetMap)]
        if not clases:
            return [{"fuente": solo, "estado": "omitido", "registros": 0,
                     "mensaje": "La fuente no está disponible para esta ejecución."}]
        resultados = [clase(conexion).ejecutar() for clase in clases]
        reevaluar_todos(conexion)
        alertas_zona(conexion)
        return resultados
    finally:
        _candado.release()


def ultima_ejecucion(conexion, geocodificar: bool = True) -> datetime | None:
    fila = conexion.execute(
        """SELECT CASE WHEN COUNT(*) = COUNT(ultima_ejecucion) THEN MIN(ultima_ejecucion) END
           FROM fuentes_datos WHERE ? OR clave != ?""", (geocodificar, FuenteOpenStreetMap.clave)).fetchone()
    return datetime.fromisoformat(fila[0]) if fila and fila[0] else None


class Planificador(threading.Thread):
    """Hilo en segundo plano: revisa cada hora si ya toca actualizar las fuentes."""

    def __init__(self, ruta_db, intervalo_horas: int, *, geocodificar: bool = True) -> None:
        super().__init__(daemon=True, name="planificador-fuentes")
        self.ruta_db = ruta_db
        self.intervalo = timedelta(hours=intervalo_horas)
        self.geocodificar = geocodificar
        self.detener = threading.Event()

    def run(self) -> None:
        while not self.detener.is_set():
            conexion = None
            try:
                conexion = conectar(self.ruta_db)
                ultima = ultima_ejecucion(conexion, self.geocodificar)
                if ultima is None or datetime.now() - ultima >= self.intervalo:
                    resultados = ejecutar_ingesta(conexion, geocodificar=self.geocodificar)
                    log.info("Lectura automática terminada: %s", resultados)
            except Exception:
                log.exception("Falló la lectura automática")
            finally:
                if conexion is not None:
                    conexion.close()
            self.detener.wait(3600)

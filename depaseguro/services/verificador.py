"""Verificador rápido: evalúa un aviso visto fuera de la plataforma (Facebook, WhatsApp, etc.)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..config import Config
from ..dao.repositorios import ImagenDAO, InmuebleDAO, ListaContactosDAO, VerificacionRapidaDAO
from ..logic.motor import BaseConocimiento
from ..models.entidades import NivelRiesgo
from .analitica import (analizar_imagen, analizar_texto, hamming, normalizar_telefono, sin_acentos,
                        telefono_valido, z_robusto)
from .evaluador import TEXTO_PATRON, TEXTO_RECOMENDACION, _reglas


@dataclass(frozen=True)
class AvisoExterno:
    texto: str
    precio_mensual: float | None = None
    area_m2: float | None = None
    tipo: str = "cuarto"
    ubigeo: str | None = None
    telefono: str = ""
    pide_pago_previo: bool = False
    tiene_contrato: bool | None = None
    permite_visita: bool | None = None
    imagen: bytes | None = None


PENALIDAD = {
    "telefono_lista_negra": 60, "imagen_clonada": 35, "pago_previo": 55, "lenguaje_evasivo": 30,
    "precio_muy_bajo": 25, "precio_bajo": 10, "lenguaje_presion": 20, "sin_contrato": 20,
    "pago_inmediato": 35, "pago_reserva": 35, "pago_solicitado": 26,
    "telefono_invalido": 10, "telefono_con_riesgo": 30, "sin_visita": 55,
}
PUNTAJE_MAXIMO_EXTERNO = 74

_MONTO = r"(?:s\s*/\.?\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s+soles)"
_CONCEPTO_PAGO = r"(?:pago|deposito|adelanto|garantia|transferencia|dinero)"
_PEDIR_TRANSFERENCIA = r"\b(?:(?:yapea|plinea|paga|deposita|abona|gira|transfiere)(?:me|nos)?)\b"
_ENVIAR_DINERO = rf"\b(?:manda|envia|pasa)(?:me|nos)?\s+(?:{_MONTO}|(?:el |un |una )?{_CONCEPTO_PAGO}\b)"
_ACCION_PAGO = (
    rf"{_PEDIR_TRANSFERENCIA}|\b(?:yapear|plinear|pagar|depositar|abonar|transferir|"
    rf"pagues|deposites|abones|yapees|transfieras)\b|{_ENVIAR_DINERO}"
)
_VER_AVISO = r"(?:visita(?:r(?:lo|la)?)?|ver(?:lo|la)?|mostrarte(?:lo|la)?|ensenarte(?:lo|la)?|conocer(?:lo|la)?)"
_RESERVAR = r"(?:separar|apartar|reservar|asegurar)(?:lo|la)?"
_ENVIO_LLAVES = r"te (?:envio|mando|mandare|enviare|hago llegar) (?:las? llaves?)"
_ENVIO_UBICACION = r"te (?:doy|paso|mando|envio|comparto) la (?:direccion|ubicacion)"
_TRAMO = r"[^.!?;\n]{0,55}?"

PAGO_ANTES_VISITA = re.compile(
    rf"(?:{_ACCION_PAGO}|\b{_CONCEPTO_PAGO}\b){_TRAMO}\b(?:antes de (?:la )?{_VER_AVISO}"
    rf"|(?:y )?(?:luego|despues) (?:te (?:muestro|enseno)|puedes {_VER_AVISO}|{_ENVIO_LLAVES}|{_ENVIO_UBICACION}))\b"
    rf"|\bpara (?:{_VER_AVISO}|agendar (?:la |una )?visita)\b{_TRAMO}(?:{_ACCION_PAGO}"
    rf"|\b(?:se (?:pide|requiere)|necesitas|hay que dar|tienes que dar|es necesario) (?:un |una )?{_CONCEPTO_PAGO}\b)"
    rf"|\b(?:te (?:muestro|enseno)|puedes {_VER_AVISO}|{_ENVIO_LLAVES})\b{_TRAMO}"
    rf"\b(?:solo )?(?:despues|luego) (?:de|del) (?:que |tu |el |la |un |una )?"
    rf"(?:me |nos )?(?:{_ACCION_PAGO}|{_CONCEPTO_PAGO})\b"
)
PAGO_POR_RESERVA = re.compile(
    rf"(?:{_ACCION_PAGO}|\b{_CONCEPTO_PAGO}\b|\b{_MONTO}){_TRAMO}\bpara {_RESERVAR}\b"
    rf"|\bpara {_RESERVAR}\b{_TRAMO}(?:{_ACCION_PAGO}|\b(?:se pide|necesitas) (?:un |una )?{_CONCEPTO_PAGO}\b)"
    rf"|\b(?:separa|aparta|reserva)(?:lo|la)? con (?:{_MONTO}|(?:un |una )?{_CONCEPTO_PAGO}\b)"
)
PAGO_URGENTE = re.compile(
    rf"(?:{_ACCION_PAGO})[\s,:-]+(?:(?:{_MONTO}|\d+)\s+)?"
    r"(?:ya(?: mismo)?|ahora(?: mismo)?|hoy(?: mismo)?|de inmediato|de una vez)\b"
)
PAGO_SOLICITADO = re.compile(rf"{_PEDIR_TRANSFERENCIA}\s+{_MONTO}|{_ENVIAR_DINERO}")
AVISO_CONTRA_PAGO = re.compile(
    r"\b(?:no|nunca|jamas)\s+(?:(?:te|me|se|debes|deberias|tienes que|hace falta|es necesario|"
    r"pedimos|pediremos|pido|cobramos|requerimos|solicitamos|hagas|realices|envies|mandes|un|una)\s+){0,4}$"
)
PAGO_TRAS_COMPROBAR = re.compile(
    rf",?\s+(?:despues de|luego de|al) (?:la |una )?(?:{_VER_AVISO}|firmar)\b"
)
VISITA_NEGADA = re.compile(
    rf"\b(?:no (?:hay|hacemos|permitimos|aceptamos) visitas?|"
    rf"no (?:se puede|se permite|puedes|podras) {_VER_AVISO}|"
    rf"no (?:te |lo |la )?(?:puedo|podemos|dejan) {_VER_AVISO}|"
    r"sin visitas?|solo (?:puedes ver|mostramos|enviamos) (?:las )?fotos)\b"
    r"(?! (?:hoy|ahora|manana|esta (?:tarde|noche)|antes d[eo]))"
)
CONTRATO_NEGADO = re.compile(
    r"\b(?:no (?:hay|habra|hacemos|firmamos|ofrezco|damos|necesitas) (?:un )?contrato|"
    r"(?:alquilo|se alquila|es|cuarto|habitacion|minidepartamento) sin contrato)\b"
    r"|(?:^|(?<=[.!?;\n]))\s*sin contrato\b"
)
LLAVES_A_DISTANCIA = re.compile(
    rf"\b(?:{_ENVIO_LLAVES}|(?:llave|llaves) (?:por|via) (?:courier|mensajeria|encomienda))\b"
)


def _pedido_de_pago(patron: re.Pattern, texto: str) -> str | None:
    for coincidencia in patron.finditer(texto):
        antes = texto[max(0, coincidencia.start() - 45):coincidencia.start()]
        resto = texto[coincidencia.end():coincidencia.end() + 50]
        despues = re.split(r"[.!?;]", resto, maxsplit=1)[0]
        frase = coincidencia.group() + despues
        if not AVISO_CONTRA_PAGO.search(antes) and not PAGO_TRAS_COMPROBAR.search(frase):
            return coincidencia.group()
    return None


def _revisar_texto(aviso: AvisoExterno) -> list[tuple]:
    limpio = " ".join(sin_acentos(aviso.texto).lower().split())
    limpio = re.sub(r"\bs\s*/\.(?=\s*\d)", "s/", limpio)
    limpio = re.sub(r"(?<=\d)\.(?=\d)", ",", limpio)
    hallazgos = []
    presion = [frase for frase in analizar_texto(limpio)["presion"] if frase not in ("hoy mismo", "no pierdas")]
    if presion:
        hallazgos.append(("lenguaje_presion", "Te apuran para decidir", ", ".join(presion)))

    # Un pago puede reunir varias señales. Se registra primero la más grave.
    pago_previo = _pedido_de_pago(PAGO_ANTES_VISITA, limpio)
    if aviso.pide_pago_previo or pago_previo:
        hallazgos.append(("pago_previo", "Pide dinero antes de la visita",
                          pago_previo or "Marcaste que te piden dinero antes de visitar."))
    elif pago_urgente := _pedido_de_pago(PAGO_URGENTE, limpio):
        hallazgos.append(("pago_inmediato", "Pide un pago inmediato", pago_urgente))
    elif pago_reserva := _pedido_de_pago(PAGO_POR_RESERVA, limpio):
        hallazgos.append(("pago_reserva", "Pide dinero para reservar", pago_reserva))
    elif pedido := _pedido_de_pago(PAGO_SOLICITADO, limpio):
        hallazgos.append(("pago_solicitado", "Solicita un envío de dinero", pedido))

    if aviso.tiene_contrato is False or CONTRATO_NEGADO.search(limpio):
        hallazgos.append(("sin_contrato", "No ofrece contrato", "Pide un contrato escrito antes de entregar dinero."))
    if aviso.permite_visita is False or VISITA_NEGADA.search(limpio):
        hallazgos.append(("sin_visita", "No permite visitar el lugar", "Visita el inmueble antes de entregar dinero."))
    if LLAVES_A_DISTANCIA.search(limpio):
        hallazgos.append(("lenguaje_evasivo", "Ofrece enviarte las llaves",
                          "Coordina una visita y comprueba quién tiene autorización para alquilar el inmueble."))
    return hallazgos


def _revisar_precio(db, aviso: AvisoExterno) -> list[tuple]:
    if not aviso.precio_mensual:
        return []
    if aviso.area_m2:
        valor = aviso.precio_mensual / aviso.area_m2
        columna = "precio_m2_pen"
    else:
        valor = aviso.precio_mensual
        columna = "precio_mensual_pen"
    sql = (f"SELECT {columna} FROM inmuebles WHERE tipo = ? AND {columna} IS NOT NULL "
           "AND estado IN ('publicado','observado')")
    parametros: tuple = (aviso.tipo,)
    distrital = [f[0] for f in db.execute(sql + " AND ubigeo = ?", (*parametros, aviso.ubigeo))] if aviso.ubigeo else []
    muestra = distrital if len(distrital) >= Config.MUESTRA_MINIMA_PRECIOS else [f[0] for f in db.execute(sql, parametros)]
    if len(muestra) < Config.MUESTRA_MINIMA_PRECIOS:
        return []
    z, mediana = z_robusto(valor, muestra)
    if z <= Config.Z_PRECIO_MUY_BAJO:
        return [("precio_muy_bajo", "Precio muy por debajo de lo habitual",
                 f"La mediana comparable es S/ {mediana:.2f} y este aviso está en S/ {valor:.2f}.")]
    if z <= Config.Z_PRECIO_BAJO:
        return [("precio_bajo", "Precio bajo para la zona",
                 f"La mediana comparable es S/ {mediana:.2f} y este aviso está en S/ {valor:.2f}.")]
    return []


def _revisar_imagen(db, aviso: AvisoExterno) -> list[tuple]:
    if aviso.imagen is None:
        return []
    datos = analizar_imagen(aviso.imagen)
    for otra in ImagenDAO(db).publicas():
        if otra["sha256"] == datos["sha256"] or hamming(otra["dhash"], datos["dhash"]) <= Config.HAMMING_IMAGEN_DUPLICADA:
            return [("imagen_clonada", "La foto ya existe en otro aviso",
                     f"Coincide con «{otra['titulo']}». Pregunta por qué aparece con otro anunciante.")]
    return []


def verificar(db, aviso: AvisoExterno, usuario_id: int | None = None) -> dict:
    hallazgos = _revisar_texto(aviso)
    if aviso.telefono:
        telefono = normalizar_telefono(aviso.telefono)
        if not telefono_valido(telefono):
            hallazgos.append(("telefono_invalido", "Número con formato extraño", "No parece un celular peruano."))
        elif ListaContactosDAO(db).contiene(telefono):
            hallazgos.append(("telefono_lista_negra", "Número con caso confirmado",
                              "Está vinculado a un reporte confirmado en DepaSeguro."))
        else:
            coincidencias = InmuebleDAO(db).contar(
                "telefono_contacto = ? AND nivel_riesgo IN ('Riesgo alto','Crítico')", (telefono,))
            if coincidencias:
                hallazgos.append(("telefono_con_riesgo", "Número usado en avisos de riesgo",
                                  f"Aparece en {coincidencias} aviso(s) con riesgo alto."))
    hallazgos += _revisar_precio(db, aviso)
    hallazgos += _revisar_imagen(db, aviso)

    base = BaseConocimiento(list(_reglas()))
    hechos = {hecho for hecho, _titulo, _detalle in hallazgos}
    for hecho in sorted(hechos):
        base.agregar_hecho(hecho, "externo")
    if {"sin_contrato", "pago_previo"} <= hechos:
        base.agregar_hecho("sin_documentos", "externo")
    patrones = [fila["P"] for fila in base.consultar("patron(externo, P)")]
    recomendaciones = [fila["R"] for fila in base.consultar("recomendacion(externo, R)")]

    puntaje = max(0, min(PUNTAJE_MAXIMO_EXTERNO, 100 - sum(PENALIDAD[hecho] for hecho in hechos) - 10 * len(patrones)))
    if base.cumple("critico(externo)"):
        puntaje = min(puntaje, 24)
    resultado = {
        "puntaje": puntaje,
        "nivel": NivelRiesgo.desde_puntaje(puntaje).value if hallazgos else "Información insuficiente",
        "hallazgos": [{"titulo": t, "detalle": d} for _h, t, d in hallazgos],
        "patrones": [TEXTO_PATRON.get(p, p) for p in patrones],
        "recomendaciones": [TEXTO_RECOMENDACION.get(r, r) for r in recomendaciones]
        or [TEXTO_RECOMENDACION["visitar_antes"]],
    }
    VerificacionRapidaDAO(db).insertar({"usuario_id": usuario_id, "puntaje": puntaje, "nivel": resultado["nivel"],
                                        "resultado": json.dumps(resultado, ensure_ascii=False)})
    return resultado

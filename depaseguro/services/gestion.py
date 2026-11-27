"""Casos de uso que modifican datos: cuentas, avisos, reseñas, reportes y moderación."""
from __future__ import annotations

import math
import re
import secrets
import threading
import uuid
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from ..dao.base import conectar, transaccion
from ..dao.repositorios import (AlertaDAO, AuditoriaDAO, BusquedaGuardadaDAO, CampusDAO, CodigoVisitaDAO,
                                DescargoDAO, DistritoDAO, DocumentoDAO, ImagenDAO, InmuebleDAO,
                                ListaContactosDAO, ReporteDAO, ResenaDAO, UsuarioDAO)
from .analitica import (ImagenInvalida, analizar_imagen, dni_valido, normalizar_precio, normalizar_telefono,
                        ruc_valido, sha256_bytes, telefono_valido)
from .evaluador import EvaluadorInmueble, tipo_cambio_vigente

SERVICIOS = ("Agua", "Luz", "Internet", "Gas", "Lavandería", "Cocina compartida", "Baño privado", "Amoblado")
TIPOS = {"cuarto": "Cuarto", "minidepartamento": "Minidepartamento", "departamento": "Departamento",
         "pension": "Pensión con alimentos"}
MOTIVOS = {"inexistente": "El inmueble no existe", "fotos_falsas": "Fotos falsas o copiadas",
           "cobro_indebido": "Cobro indebido", "suplantacion": "Suplantación del dueño",
           "condiciones_abusivas": "Condiciones abusivas", "otro": "Otro motivo"}
EXTENSIONES_DOCUMENTO = {".pdf", ".jpg", ".jpeg", ".png"}


class ErrorNegocio(ValueError):
    """Error de validación que se muestra tal cual al usuario."""


def _exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise ErrorNegocio(mensaje)


def _numero(valor, campo: str, minimo: float = 0) -> float:
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ErrorNegocio(f"{campo} debe ser un número.") from None
    _exigir(math.isfinite(numero), f"{campo} debe ser un número finito.")
    _exigir(numero >= minimo, f"{campo} debe ser mayor o igual a {minimo:g}.")
    return numero


# --- Cuentas -------------------------------------------------------------------
def registrar_usuario(db, datos: dict) -> int:
    email = datos.get("email", "").strip().lower()
    clave = datos.get("password", "")
    rol = datos.get("rol", "estudiante")
    _exigir(len(datos.get("nombre", "").strip()) >= 3, "Escribe tu nombre completo.")
    _exigir(bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)), "El correo no es válido.")
    _exigir(len(clave) >= 8 and re.search(r"\d", clave) and re.search(r"[A-Za-z]", clave),
            "La contraseña debe tener al menos 8 caracteres, con letras y números.")
    _exigir(rol in ("estudiante", "arrendador"), "Rol no permitido.")
    usuarios = UsuarioDAO(db)
    tipo_doc, num_doc = datos.get("tipo_doc") or None, (datos.get("num_doc") or "").strip() or None
    if rol == "arrendador":
        _exigir(tipo_doc in ("DNI", "RUC"), "Indica tu DNI o RUC.")
        valido = dni_valido(num_doc) if tipo_doc == "DNI" else ruc_valido(num_doc)
        _exigir(valido, f"El {tipo_doc} no tiene un formato válido.")
    else:
        tipo_doc = num_doc = None
    telefono = normalizar_telefono(datos.get("telefono", ""))
    if telefono:
        _exigir(telefono_valido(telefono), "Escribe un celular de 9 dígitos.")
    hash_clave = generate_password_hash(clave)
    with transaccion(db):
        _exigir(usuarios.por_email(email) is None, "Ya existe una cuenta con ese correo.")
        identificador = usuarios.insertar({
            "nombre": datos["nombre"].strip(), "email": email, "password_hash": hash_clave,
            "rol": rol, "telefono": telefono or None, "tipo_doc": tipo_doc, "num_doc": num_doc})
        AuditoriaDAO(db).registrar(identificador, "registro", "usuario", identificador)
    return identificador


def autenticar(db, email: str, clave: str) -> dict | None:
    usuario = UsuarioDAO(db).por_email(email or "")
    if usuario and usuario["activo"] and check_password_hash(usuario["password_hash"], clave or ""):
        return usuario
    return None


def actualizar_perfil(db, usuario_id: int, datos: dict, foto=None) -> None:
    """Actualiza los datos personales y reemplaza la foto sin dejar archivos huérfanos."""
    nombre = datos.get("nombre", "").strip()
    email = datos.get("email", "").strip().lower()
    telefono = normalizar_telefono(datos.get("telefono", ""))
    _exigir(3 <= len(nombre) <= 120, "Escribe tu nombre completo.")
    _exigir(len(email) <= 254 and bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)),
            "El correo no es válido.")
    if telefono:
        _exigir(telefono_valido(telefono), "Escribe un celular de 9 dígitos.")

    usuarios = UsuarioDAO(db)
    actual = usuarios.obtener(usuario_id)
    _exigir(actual is not None, "La cuenta ya no existe.")
    existente = usuarios.por_email(email)
    _exigir(existente is None or existente["id"] == usuario_id, "Ya existe una cuenta con ese correo.")

    foto_nueva = foto if foto is not None and foto.filename else None
    quitar_foto = bool(datos.get("quitar_foto")) and foto_nueva is None
    anterior = actual.get("foto_perfil")
    nombre_archivo = None
    with ExitStack() as archivos:
        if foto_nueva is not None:
            contenido = foto_nueva.read()
            _exigir(bool(contenido), "La foto está vacía.")
            _exigir(len(contenido) <= 3 * 1024 * 1024, "La foto no debe superar 3 MB.")
            try:
                informacion = analizar_imagen(contenido)
            except ImagenInvalida as error:
                raise ErrorNegocio("La foto debe ser una imagen JPG, PNG o WEBP válida.") from error
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[informacion["formato"]]
            nombre_archivo = _guardar_archivo("UPLOAD_PERFILES", extension, contenido, archivos)

        cambios = {"nombre": nombre, "email": email, "telefono": telefono or None}
        if foto_nueva is not None:
            cambios["foto_perfil"] = nombre_archivo
        elif quitar_foto:
            cambios["foto_perfil"] = None
        with transaccion(db):
            usuarios.actualizar(usuario_id, cambios)
            AuditoriaDAO(db).registrar(usuario_id, "actualizar_perfil", "usuario", usuario_id)
        archivos.pop_all()

    if anterior and (foto_nueva is not None or quitar_foto):
        try:
            (Path(current_app.config["UPLOAD_PERFILES"]) / anterior).unlink(missing_ok=True)
        except OSError:
            pass


# --- Avisos --------------------------------------------------------------------
def _validar_aviso(db, formulario) -> dict:
    titulo = formulario.get("titulo", "").strip()
    descripcion = formulario.get("descripcion", "").strip()
    telefono = normalizar_telefono(formulario.get("telefono_contacto", ""))
    _exigir(len(titulo) >= 8, "El título debe tener al menos 8 caracteres.")
    _exigir(len(descripcion) >= 30, "La descripción debe tener al menos 30 caracteres.")
    _exigir(formulario.get("tipo") in TIPOS, "Elige un tipo de inmueble.")
    _exigir(DistritoDAO(db).obtener(formulario.get("ubigeo")) is not None, "Elige un distrito válido.")
    _exigir(len(formulario.get("direccion", "").strip()) >= 6, "Escribe la dirección.")
    _exigir(telefono_valido(telefono), "Escribe un celular de contacto de 9 dígitos.")
    _exigir(formulario.get("moneda") in ("PEN", "USD"), "Moneda no válida.")
    _exigir(formulario.get("periodo") in ("semana", "mes", "semestre", "anio"), "Periodo no válido.")
    lat, lon = formulario.get("lat") or None, formulario.get("lon") or None
    _exigir((lat is None) == (lon is None), "Marca el punto completo en el mapa.")
    if lat is not None:
        lat, lon = _numero(lat, "La latitud", -90), _numero(lon, "La longitud", -180)
        _exigir(lat <= 90 and lon <= 180, "Las coordenadas están fuera del rango permitido.")
    area = _numero(formulario.get("area_m2"), "El área", 4)
    precio = _numero(formulario.get("precio"), "El precio", 1)
    try:
        normalizar_precio(precio, formulario["moneda"], formulario["periodo"], area, tipo_cambio_vigente(db))
    except ValueError as error:
        raise ErrorNegocio(str(error)) from error
    return {
        "titulo": titulo, "descripcion": descripcion, "tipo": formulario["tipo"], "ubigeo": formulario["ubigeo"],
        "direccion": formulario["direccion"].strip(), "telefono_contacto": telefono,
        "lat": lat, "lon": lon, "area_m2": area, "precio": precio,
        "moneda": formulario["moneda"], "periodo": formulario["periodo"],
        "adelanto_meses": _numero(formulario.get("adelanto_meses", 1), "El adelanto"),
        "garantia_meses": _numero(formulario.get("garantia_meses", 1), "La garantía"),
        "pago_previo_visita": 1 if formulario.get("pago_previo_visita") else 0,
        "contrato_escrito": 1 if formulario.get("contrato_escrito") else 0,
    }


def _guardar_archivo(carpeta: str, extension: str, contenido: bytes, archivos: ExitStack) -> str:
    nombre = f"{uuid.uuid4().hex[:20]}{extension}"
    ruta = Path(current_app.config[carpeta]) / nombre
    archivos.callback(ruta.unlink, missing_ok=True)
    ruta.write_bytes(contenido)
    return nombre


def _guardar_imagenes(db, inmueble_id: int, imagenes: list, archivos: ExitStack) -> None:
    for archivo in imagenes:
        if not archivo or not archivo.filename:
            continue
        contenido = archivo.read()
        try:
            datos = analizar_imagen(contenido)
        except ImagenInvalida as error:
            raise ErrorNegocio("Uno de los archivos no es una imagen JPG, PNG o WEBP válida.") from error
        extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[datos["formato"]]
        nombre = _guardar_archivo("UPLOAD_IMAGENES", extension, contenido, archivos)
        ImagenDAO(db).insertar({"inmueble_id": inmueble_id, "archivo": nombre, **datos})


def guardar_documento(db, inmueble_id: int, tipo: str, archivo) -> None:
    _exigir(tipo in ("titularidad", "recibo_servicio", "identidad"), "Tipo de documento no válido.")
    _exigir(archivo is not None and archivo.filename, "Selecciona un documento.")
    extension = Path(archivo.filename).suffix.lower()
    _exigir(extension in EXTENSIONES_DOCUMENTO, "El documento debe ser PDF, JPG o PNG.")
    contenido = archivo.read()
    _exigir(bool(contenido), "El documento está vacío.")
    if extension == ".pdf":
        _exigir(contenido.startswith(b"%PDF-") and contenido.rstrip().endswith(b"%%EOF"),
                "El archivo no es un PDF válido.")
    else:
        try:
            formato = analizar_imagen(contenido)["formato"]
        except ImagenInvalida as error:
            raise ErrorNegocio("El documento debe ser una imagen JPG o PNG válida.") from error
        _exigir(formato == ("PNG" if extension == ".png" else "JPEG"),
                "El contenido del documento no coincide con su extensión.")
    with ExitStack() as archivos:
        with transaccion(db):
            nombre = _guardar_archivo("UPLOAD_DOCUMENTOS", extension, contenido, archivos)
            DocumentoDAO(db).insertar({"inmueble_id": inmueble_id, "tipo": tipo, "archivo": nombre,
                                       "sha256": sha256_bytes(contenido)})
            EvaluadorInmueble(db).evaluar(inmueble_id)
        archivos.pop_all()


def crear_aviso(db, arrendador_id: int, formulario, servicios: list[str], imagenes: list) -> int:
    datos = _validar_aviso(db, formulario)
    inmuebles = InmuebleDAO(db)
    with ExitStack() as archivos:
        with transaccion(db):
            identificador = inmuebles.insertar({**datos, "arrendador_id": arrendador_id, "estado": "pendiente"})
            inmuebles.fijar_servicios(identificador, [s for s in servicios if s in SERVICIOS])
            _guardar_imagenes(db, identificador, imagenes, archivos)
            AuditoriaDAO(db).registrar(arrendador_id, "crear", "inmueble", identificador)
            EvaluadorInmueble(db).evaluar(identificador)
        archivos.pop_all()
    verificar_direccion_en_segundo_plano(identificador)
    return identificador


def editar_aviso(db, inmueble_id: int, usuario_id: int, formulario, servicios: list[str], imagenes: list) -> None:
    inmuebles = InmuebleDAO(db)
    datos = _validar_aviso(db, formulario)
    with ExitStack() as archivos:
        with transaccion(db):
            actual = inmuebles.obtener(inmueble_id)
            _exigir(actual is not None and actual["arrendador_id"] == usuario_id, "No puedes editar este aviso.")
            if any(datos[campo] != actual[campo] for campo in ("direccion", "ubigeo", "lat", "lon")):
                datos["direccion_estado"] = "sin_verificar"
                if (datos["direccion"], datos["ubigeo"]) != (actual["direccion"], actual["ubigeo"]):
                    if (datos["lat"], datos["lon"]) == (actual["lat"], actual["lon"]):
                        datos.update(lat=None, lon=None)
            datos["actualizado_en"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            inmuebles.actualizar(inmueble_id, datos)
            inmuebles.fijar_servicios(inmueble_id, [s for s in servicios if s in SERVICIOS])
            _guardar_imagenes(db, inmueble_id, imagenes, archivos)
            AuditoriaDAO(db).registrar(usuario_id, "editar", "inmueble", inmueble_id)
            EvaluadorInmueble(db).evaluar(inmueble_id)
        archivos.pop_all()
    if datos.get("direccion_estado") == "sin_verificar":
        verificar_direccion_en_segundo_plano(inmueble_id)


def eliminar_aviso(db, inmueble_id: int, usuario_id: int) -> None:
    inmuebles = InmuebleDAO(db)
    actual = inmuebles.obtener(inmueble_id)
    _exigir(actual is not None and actual["arrendador_id"] == usuario_id, "No puedes eliminar este aviso.")
    inmuebles.actualizar(inmueble_id, {"estado": "retirado"})
    AuditoriaDAO(db).registrar(usuario_id, "retirar", "inmueble", inmueble_id)


def verificar_direccion_en_segundo_plano(inmueble_id: int) -> None:
    """Consulta OpenStreetMap sin hacer esperar al usuario."""
    if not current_app.config.get("GEOCODIFICAR", True) or current_app.config.get("TESTING"):
        return
    ruta = current_app.config["DB_PATH"]

    def tarea() -> None:
        from ..ingestion.fuentes import FuenteOpenStreetMap

        conexion = conectar(ruta)
        try:
            resultado = FuenteOpenStreetMap(conexion, inmueble_id=inmueble_id).ejecutar()
            if resultado["estado"] == "ok" and resultado["registros"]:
                EvaluadorInmueble(conexion).evaluar(inmueble_id)
        finally:
            conexion.close()

    threading.Thread(target=tarea, daemon=True).start()


def generar_codigo_visita(db, inmueble_id: int, usuario_id: int) -> str:
    aviso = InmuebleDAO(db).obtener(inmueble_id)
    _exigir(aviso is not None and aviso["arrendador_id"] == usuario_id, "No puedes generar este código.")
    with transaccion(db):
        while True:
            codigo = secrets.token_hex(3).upper()
            if db.execute("INSERT OR IGNORE INTO codigos_visita(inmueble_id, codigo) VALUES (?,?)",
                          (inmueble_id, codigo)).rowcount:
                return codigo


# --- Comunidad -----------------------------------------------------------------
def registrar_resena(db, inmueble_id: int, estudiante_id: int, puntaje, comentario: str, codigo: str = "") -> bool:
    valor = _numero(puntaje, "El puntaje", 1)
    _exigir(valor.is_integer() and valor <= 5, "El puntaje debe ser un entero de 1 a 5.")
    _exigir(len(comentario.strip()) >= 15, "Cuenta tu experiencia en al menos 15 caracteres.")
    resenas = ResenaDAO(db)
    verificada = bool(codigo.strip())
    with transaccion(db):
        _exigir(resenas.contar("inmueble_id = ? AND estudiante_id = ?", (inmueble_id, estudiante_id)) == 0,
                "Ya dejaste una reseña en este aviso.")
        if verificada:
            codigos = CodigoVisitaDAO(db)
            registro = codigos.por_codigo(codigo)
            _exigir(registro is not None and registro["inmueble_id"] == inmueble_id and registro["usado_por"] is None,
                    "El código de visita no es válido o ya fue usado.")
            codigos.actualizar(registro["id"], {"usado_por": estudiante_id,
                                                "usado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        resenas.insertar({"inmueble_id": inmueble_id, "estudiante_id": estudiante_id, "puntaje": int(valor),
                          "comentario": comentario.strip(), "verificada": int(verificada)})
        EvaluadorInmueble(db).evaluar(inmueble_id)
    return verificada


def guardar_busqueda(db, usuario_id: int, datos) -> None:
    campus_id = datos.get("campus_id", type=int)
    _exigir(CampusDAO(db).obtener(campus_id) is not None, "Elige un campus válido.")
    confianza = _numero(datos.get("trust_min") or 60, "El puntaje mínimo")
    _exigir(confianza.is_integer() and confianza <= 100, "El puntaje mínimo debe ser un entero de 0 a 100.")
    BusquedaGuardadaDAO(db).insertar({
        "usuario_id": usuario_id, "campus_id": campus_id,
        "radio_km": _numero(datos.get("radio_km") or 2, "El radio", 0.2),
        "precio_max": _numero(datos.get("precio_max") or 800, "El precio máximo", 1),
        "trust_min": int(confianza)})


def registrar_reporte(db, inmueble_id: int, usuario_id: int, datos: dict) -> int:
    _exigir(datos.get("motivo") in MOTIVOS, "Elige un motivo.")
    _exigir(len(datos.get("detalle", "").strip()) >= 20, "Describe lo ocurrido en al menos 20 caracteres.")
    telefono = normalizar_telefono(datos.get("telefono_reportado", ""))
    _exigir(not datos.get("telefono_reportado", "").strip() or telefono_valido(telefono),
            "Escribe un celular reportado de 9 dígitos.")
    monto = _numero(datos.get("monto_perdido") or 0, "El monto")
    with transaccion(db):
        identificador = ReporteDAO(db).insertar({
            "inmueble_id": inmueble_id, "reportante_id": usuario_id, "motivo": datos["motivo"],
            "detalle": datos["detalle"].strip(), "telefono_reportado": telefono or None, "monto_perdido": monto})
        AlertaDAO(db).registrar("reporte_nuevo", "alta", f"Nuevo reporte #{identificador}: {MOTIVOS[datos['motivo']]}.",
                                inmueble_id=inmueble_id, clave=f"reporte:{identificador}")
        AuditoriaDAO(db).registrar(usuario_id, "reportar", "reporte", identificador)
        EvaluadorInmueble(db).evaluar(inmueble_id)
    return identificador


def responder_reporte(db, reporte_id: int, arrendador_id: int, texto: str) -> None:
    reporte = ReporteDAO(db).con_detalle("r.id = ?", (reporte_id,))
    _exigir(bool(reporte) and reporte[0]["arrendador_id"] == arrendador_id, "No puedes responder este reporte.")
    _exigir(len(texto.strip()) >= 15, "Escribe tu descargo con más detalle.")
    DescargoDAO(db).insertar({"reporte_id": reporte_id, "arrendador_id": arrendador_id, "texto": texto.strip()})
    AlertaDAO(db).registrar("descargo", "media", f"El arrendador respondió el reporte #{reporte_id}.",
                            inmueble_id=reporte[0]["inmueble_id"], clave=f"descargo:{reporte_id}")


# --- Moderación ----------------------------------------------------------------
def resolver_reporte(db, reporte_id: int, admin_id: int, estado: str, resolucion: str) -> None:
    _exigir(estado in ("en_revision", "confirmado", "descartado"), "Estado no válido.")
    reportes = ReporteDAO(db)
    lista = ListaContactosDAO(db)
    with transaccion(db):
        reporte = reportes.obtener(reporte_id)
        _exigir(reporte is not None, "El reporte no existe.")
        aviso = InmuebleDAO(db).obtener(reporte["inmueble_id"])
        telefono = reporte["telefono_reportado"] or (aviso["telefono_contacto"] if aviso else None)
        cambios = {"estado": estado, "resolucion": resolucion.strip() or None,
                   "resuelto_en": None if estado == "en_revision" else datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        if estado == "confirmado" and telefono_valido(telefono):
            cambios["telefono_reportado"] = telefono
            if not lista.contiene(telefono):
                lista.insertar({"telefono": telefono, "reporte_id": reporte_id, "motivo": MOTIVOS[reporte["motivo"]]})
        reportes.actualizar(reporte_id, cambios)
        afectados = {aviso["id"]} if aviso else set()
        if estado != "confirmado" and reporte["estado"] == "confirmado":
            for contacto in db.execute("SELECT id, telefono FROM lista_contactos WHERE reporte_id = ?",
                                       (reporte_id,)).fetchall():
                telefono = contacto["telefono"]
                respaldo = db.execute(
                    """SELECT r.id, r.motivo FROM reportes r LEFT JOIN inmuebles i ON i.id = r.inmueble_id
                       WHERE r.estado = 'confirmado' AND COALESCE(r.telefono_reportado, i.telefono_contacto) = ?
                       ORDER BY r.id LIMIT 1""", (telefono,)).fetchone()
                if respaldo:
                    lista.actualizar(contacto["id"], {"reporte_id": respaldo["id"], "motivo": MOTIVOS[respaldo["motivo"]]})
                else:
                    lista.eliminar(contacto["id"])
        afectados.update(fila["id"] for fila in db.execute(
            "SELECT id FROM inmuebles WHERE telefono_contacto = ?", (telefono,)))
        AuditoriaDAO(db).registrar(admin_id, f"reporte_{estado}", "reporte", reporte_id, resolucion)
        evaluador = EvaluadorInmueble(db)
        for inmueble_id in sorted(afectados):
            evaluador.evaluar(inmueble_id)


def revisar_documento(db, documento_id: int, admin_id: int, estado: str, observacion: str = "") -> None:
    _exigir(estado in ("aprobado", "rechazado"), "Estado no válido.")
    documentos = DocumentoDAO(db)
    with transaccion(db):
        documento = documentos.obtener(documento_id)
        _exigir(documento is not None, "El documento no existe.")
        documentos.actualizar(documento_id, {
            "estado": estado, "observacion": observacion.strip() or None, "revisado_por": admin_id,
            "revisado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        AuditoriaDAO(db).registrar(admin_id, f"documento_{estado}", "documento", documento_id, observacion)
        EvaluadorInmueble(db).evaluar(documento["inmueble_id"])


def cambiar_estado_aviso(db, inmueble_id: int, admin_id: int, estado: str) -> None:
    _exigir(estado in ("publicado", "observado", "rechazado", "pendiente"), "Estado no válido.")
    inmuebles = InmuebleDAO(db)
    with transaccion(db):
        _exigir(inmuebles.obtener(inmueble_id) is not None, "El aviso no existe.")
        inmuebles.actualizar(inmueble_id, {"estado": estado})
        AuditoriaDAO(db).registrar(admin_id, f"aviso_{estado}", "inmueble", inmueble_id)
        EvaluadorInmueble(db).evaluar(inmueble_id)


def cambiar_usuario(db, usuario_id: int, admin_id: int, cambios: dict) -> None:
    permitidos = {clave: valor for clave, valor in cambios.items() if clave in ("verificado", "activo")}
    _exigir(bool(permitidos), "Sin cambios.")
    _exigir(all(str(valor) in ("0", "1") for valor in permitidos.values()), "El valor debe ser 0 o 1.")
    permitidos = {clave: int(valor) for clave, valor in permitidos.items()}
    _exigir(UsuarioDAO(db).obtener(usuario_id) is not None, "El usuario no existe.")
    _exigir(not (usuario_id == admin_id and permitidos.get("activo") == 0), "No puedes desactivar tu propia cuenta.")
    UsuarioDAO(db).actualizar(usuario_id, permitidos)
    AuditoriaDAO(db).registrar(admin_id, "actualizar_usuario", "usuario", usuario_id, str(permitidos))
    evaluador = EvaluadorInmueble(db)
    for fila in db.execute("SELECT id FROM inmuebles WHERE arrendador_id = ?", (usuario_id,)).fetchall():
        evaluador.evaluar(fila["id"])

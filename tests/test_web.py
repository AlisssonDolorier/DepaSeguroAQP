"""Pruebas de flujos completos a través de la aplicación web."""
import io
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from depaseguro.dao.repositorios import DocumentoDAO, InmuebleDAO, ListaContactosDAO, ReporteDAO, UsuarioDAO
from .conftest import CLAVE, agregar_foto, crear_aviso, crear_usuario, evaluar, foto, ingresar, token


def formulario_aviso(csrf, **cambios):
    datos = {"csrf_token": csrf, "titulo": "Cuarto cerca de la UTP", "descripcion": "Cuarto limpio con contrato y visita previa.",
             "tipo": "cuarto", "ubigeo": "040101", "direccion": "Calle Prueba 123", "telefono_contacto": "987 111 222",
             "area_m2": "14", "precio": "500", "moneda": "PEN", "periodo": "mes", "adelanto_meses": "1",
             "garantia_meses": "1", "contrato_escrito": "on", "lat": "-16.40", "lon": "-71.53", "servicios": ["Agua", "Luz"]}
    datos.update(cambios)
    return datos


@pytest.mark.parametrize("ruta", ["/", "/inmuebles", "/mapa", "/verificador", "/zonas", "/fuentes", "/contrato", "/blog",
                                  "/nosotros", "/terminos", "/contacto", "/login", "/registro", "/api/mapa", "/api/zonas/serie"])
def test_paginas_publicas(cliente, ruta):
    assert cliente.get(ruta).status_code == 200


def test_catalogo_muestra_solo_zonas_con_avisos_y_cantidades(cliente, db):
    dueno = crear_usuario(db, "zonas@prueba.test")
    aviso = crear_aviso(db, dueno, ubigeo="040101", estado="publicado")
    evaluar(db, aviso)
    html = cliente.get("/inmuebles").get_data(as_text=True)
    assert "Zona o distrito" in html
    assert "Cercado de Arequipa" in html and "(1)" in html
    assert "Characato" not in html

    filtrado = cliente.get("/inmuebles?ubigeo=040101").get_data(as_text=True)
    assert "Cuarto de prueba" in filtrado


def test_catalogo_muestra_campus_y_no_filtra_por_trust_score(cliente, db):
    db.execute(
        """INSERT INTO campus(universidad, codigo_local, distrito, lat, lon, licencia)
           VALUES ('Universidad de prueba', 'AQP01', 'AREQUIPA', -16.40, -71.53, 'LICENCIADA')"""
    )
    dueno = crear_usuario(db, "campus@prueba.test")
    aviso = crear_aviso(db, dueno, estado="publicado")
    evaluar(db, aviso)
    html = cliente.get("/inmuebles?trust_min=100").get_data(as_text=True)
    assert "Universidad de Prueba (AQP01)" in html
    assert 'name="trust_min"' not in html
    assert "Cuarto de prueba" in html


def test_catalogo_acepta_precio_maximo_de_500_soles(cliente, db):
    dueno = crear_usuario(db, "precio@prueba.test")
    dentro = crear_aviso(db, dueno, titulo="Cuarto de 500 soles", precio=500, estado="publicado")
    fuera = crear_aviso(db, dueno, titulo="Cuarto de 501 soles", precio=501, estado="publicado")
    evaluar(db, dentro)
    evaluar(db, fuera)
    respuesta = cliente.get("/inmuebles?precio_max=500")
    html = respuesta.get_data(as_text=True)
    assert 'name="precio_max" min="1" step="1" value="500"' in html
    assert "Cuarto de 500 soles" in html
    assert "Cuarto de 501 soles" not in html


def test_pagina_inexistente(cliente):
    assert cliente.get("/nada").status_code == 404


def test_post_sin_csrf_es_rechazado(cliente):
    assert cliente.post("/login", data={"email": "a@b.c", "password": "x"}).status_code == 403


def test_registro_inicio_y_cierre_de_sesion(cliente, db):
    datos = {"csrf_token": token(cliente, "/registro"), "nombre": "Ana Prueba", "email": "ANA@prueba.test",
             "password": "Segura123", "rol": "estudiante", "telefono": ""}
    assert cliente.post("/registro", data=datos).status_code == 302
    fila = UsuarioDAO(db).por_email("ana@prueba.test")
    assert fila and fila["password_hash"] != "Segura123"
    respuesta = cliente.post("/login", data={"email": "ana@prueba.test", "password": "Segura123", "csrf_token": token(cliente)})
    assert respuesta.headers["Location"].endswith("/estudiante/")
    assert cliente.post("/logout", data={"csrf_token": token(cliente, "/estudiante/")}).status_code == 302
    assert cliente.get("/estudiante/").status_code == 302


def test_estudiante_actualiza_datos_foto_y_puede_quitarla(cliente, db, app):
    usuario_id = crear_usuario(db, "perfil@prueba.test", "estudiante")
    ingresar(cliente, "perfil@prueba.test")
    assert "Editar mi perfil" in cliente.get("/estudiante/").get_data(as_text=True)

    respuesta = cliente.post("/perfil", data={
        "csrf_token": token(cliente, "/perfil"), "nombre": "Ana Perfil", "email": "ana@prueba.test",
        "telefono": "987 654 321", "foto": (io.BytesIO(foto(9)), "ana.jpg")},
        content_type="multipart/form-data")
    assert respuesta.status_code == 302
    actualizado = UsuarioDAO(db).obtener(usuario_id)
    assert actualizado["nombre"] == "Ana Perfil"
    assert actualizado["email"] == "ana@prueba.test"
    assert actualizado["telefono"] == "987654321"
    assert actualizado["foto_perfil"].endswith(".jpg")
    ruta_foto = Path(app.config["UPLOAD_PERFILES"]) / actualizado["foto_perfil"]
    assert ruta_foto.exists()
    imagen = cliente.get("/perfil/foto")
    assert imagen.status_code == 200 and imagen.mimetype == "image/jpeg"
    imagen.close()

    respuesta = cliente.post("/perfil", data={
        "csrf_token": token(cliente, "/perfil"), "nombre": "Ana Perfil", "email": "ana@prueba.test",
        "telefono": "987654321", "quitar_foto": "1"})
    assert respuesta.status_code == 302
    assert UsuarioDAO(db).obtener(usuario_id)["foto_perfil"] is None
    assert not ruta_foto.exists()
    assert cliente.get("/perfil/foto").status_code == 404


def test_perfil_rechaza_correo_duplicado_e_imagen_invalida(cliente, db, app):
    usuario_id = crear_usuario(db, "propio@prueba.test", "estudiante")
    crear_usuario(db, "ocupado@prueba.test", "estudiante")
    ingresar(cliente, "propio@prueba.test")

    duplicado = cliente.post("/perfil", data={
        "csrf_token": token(cliente, "/perfil"), "nombre": "Nombre Correcto",
        "email": "ocupado@prueba.test", "telefono": ""})
    assert duplicado.status_code == 400
    assert "Ya existe" in duplicado.get_data(as_text=True)
    assert UsuarioDAO(db).obtener(usuario_id)["email"] == "propio@prueba.test"

    invalida = cliente.post("/perfil", data={
        "csrf_token": token(cliente, "/perfil"), "nombre": "Nombre Correcto",
        "email": "nuevo@prueba.test", "telefono": "", "foto": (io.BytesIO(b"no es imagen"), "foto.jpg")},
        content_type="multipart/form-data")
    assert invalida.status_code == 400
    assert "imagen JPG, PNG o WEBP válida" in invalida.get_data(as_text=True)
    actual = UsuarioDAO(db).obtener(usuario_id)
    assert actual["email"] == "propio@prueba.test" and actual["foto_perfil"] is None
    assert list(Path(app.config["UPLOAD_PERFILES"]).iterdir()) == []


@pytest.mark.parametrize("cambio,mensaje", [({"password": "corta"}, "contraseña"), ({"email": "malo"}, "correo"),
                                            ({"rol": "admin"}, "Rol")])
def test_registro_valida(cliente, cambio, mensaje):
    datos = {"csrf_token": token(cliente, "/registro"), "nombre": "Ana Prueba", "email": "ana@prueba.test",
             "password": "Segura123", "rol": "estudiante", **cambio}
    respuesta = cliente.post("/registro", data=datos)
    assert respuesta.status_code == 400 and mensaje in respuesta.get_data(as_text=True)


def test_arrendador_exige_documento_valido(cliente):
    datos = {"csrf_token": token(cliente, "/registro"), "nombre": "Dueño Prueba", "email": "d@prueba.test",
             "password": "Segura123", "rol": "arrendador", "tipo_doc": "RUC", "num_doc": "20000000002"}
    assert "RUC" in cliente.post("/registro", data=datos).get_data(as_text=True)


def test_clave_incorrecta_y_bloqueo(cliente, db):
    crear_usuario(db, "bloqueo@prueba.test")
    for _ in range(6):
        respuesta = cliente.post("/login", data={"email": "bloqueo@prueba.test", "password": "mala", "csrf_token": token(cliente)})
        assert respuesta.status_code == 401
    respuesta = cliente.post("/login", data={"email": "bloqueo@prueba.test", "password": CLAVE, "csrf_token": token(cliente)})
    assert respuesta.status_code == 429


def test_redireccion_externa_bloqueada(cliente, db):
    crear_usuario(db, "seguro@prueba.test", "estudiante")
    respuesta = cliente.post("/login?siguiente=//malo.test", data={"email": "seguro@prueba.test", "password": CLAVE, "csrf_token": token(cliente)})
    assert "malo.test" not in respuesta.headers["Location"]


@pytest.mark.parametrize("ruta", ["/admin/", "/admin/usuarios", "/admin/fuentes", "/admin/exportar/catalogo.xlsx"])
def test_estudiante_no_entra_a_admin(cliente, db, ruta):
    crear_usuario(db, "curioso@prueba.test", "estudiante")
    ingresar(cliente, "curioso@prueba.test")
    assert cliente.get(ruta).status_code == 403


def test_flujo_arrendador_crea_edita_y_retira(cliente, db):
    crear_usuario(db, "dueno@prueba.test")
    ingresar(cliente, "dueno@prueba.test")
    csrf = token(cliente, "/arrendador/inmuebles/nuevo")
    datos = formulario_aviso(csrf, imagenes=(io.BytesIO(foto(1)), "cuarto.jpg"))
    respuesta = cliente.post("/arrendador/inmuebles/nuevo", data=datos, content_type="multipart/form-data")
    assert respuesta.status_code == 302
    aviso = InmuebleDAO(db).detalle(1)
    assert aviso["telefono_contacto"] == "987111222" and aviso["trust_score"] is not None and aviso["portada"]
    assert InmuebleDAO(db).servicios(1) == ["Agua", "Luz"]

    cliente.post("/arrendador/inmuebles/1/editar", data=formulario_aviso(csrf, precio="600"), content_type="multipart/form-data")
    assert InmuebleDAO(db).obtener(1)["precio_mensual_pen"] == 600

    documento = io.BytesIO()
    pdf = canvas.Canvas(documento)
    pdf.drawString(72, 750, "Documento de prueba")
    pdf.save()
    documento.seek(0)
    cliente.post("/arrendador/inmuebles/1/documentos", content_type="multipart/form-data",
                 data={"csrf_token": csrf, "tipo": "titularidad", "archivo": (documento, "titulo.pdf")})
    assert len(DocumentoDAO(db).de_inmueble(1)) == 1

    cliente.post("/arrendador/inmuebles/1/eliminar", data={"csrf_token": csrf})
    assert InmuebleDAO(db).obtener(1)["estado"] == "retirado"


def test_aviso_con_archivo_invalido_muestra_error(cliente, db, app):
    crear_usuario(db, "archivo@prueba.test")
    ingresar(cliente, "archivo@prueba.test")
    csrf = token(cliente, "/arrendador/inmuebles/nuevo")
    datos = formulario_aviso(csrf, imagenes=[(io.BytesIO(foto(1)), "foto.jpg"), (io.BytesIO(b"no imagen"), "x.jpg")])
    respuesta = cliente.post("/arrendador/inmuebles/nuevo", data=datos, content_type="multipart/form-data", follow_redirects=True)
    assert "imagen" in respuesta.get_data(as_text=True)
    assert InmuebleDAO(db).contar() == 0
    assert list(app.config["UPLOAD_IMAGENES"].iterdir()) == []


def test_edicion_con_foto_invalida_conserva_el_aviso(cliente, db, app):
    dueno = crear_usuario(db, "edicion@prueba.test")
    aviso = crear_aviso(db, dueno)
    ingresar(cliente, "edicion@prueba.test")
    ruta = f"/arrendador/inmuebles/{aviso}/editar"
    datos = formulario_aviso(token(cliente, ruta), precio="700", imagenes=(io.BytesIO(b"invalida"), "foto.jpg"))
    cliente.post(ruta, data=datos, content_type="multipart/form-data")
    assert InmuebleDAO(db).obtener(aviso)["precio"] == 450
    assert InmuebleDAO(db).servicios(aviso) == []
    assert list(app.config["UPLOAD_IMAGENES"].iterdir()) == []


@pytest.mark.parametrize("cambios", [{"lat": "texto"}, {"lon": ""}, {"precio": "inf"}, {"ubigeo": "999999"}])
def test_aviso_rechaza_datos_invalidos_sin_guardar(cliente, db, cambios):
    crear_usuario(db, "entrada@prueba.test")
    ingresar(cliente, "entrada@prueba.test")
    ruta = "/arrendador/inmuebles/nuevo"
    respuesta = cliente.post(ruta, data=formulario_aviso(token(cliente, ruta), **cambios))
    assert respuesta.status_code == 302
    assert InmuebleDAO(db).contar() == 0


def test_foto_de_aviso_pendiente_visible_solo_al_arrendador(cliente, db, app):
    crear_usuario(db, "privado@prueba.test")
    ingresar(cliente, "privado@prueba.test")
    ruta = "/arrendador/inmuebles/nuevo"
    datos = formulario_aviso(token(cliente, ruta), imagenes=(io.BytesIO(foto(1)), "cuarto.jpg"))
    cliente.post(ruta, data=datos)
    portada = InmuebleDAO(db).detalle(1)["portada"]
    assert cliente.get(f"/media/{portada}").status_code == 200
    visitante = app.test_client()
    assert visitante.get(f"/media/{portada}").status_code == 404
    InmuebleDAO(db).actualizar(1, {"estado": "publicado"})
    assert visitante.get(f"/media/{portada}").status_code == 200


def test_token_csrf_no_ascii_se_rechaza(cliente):
    token(cliente)
    assert cliente.post("/login", data={"csrf_token": "válido"}).status_code == 403


def test_arrendador_no_gestiona_aviso_ajeno(cliente, db):
    ajeno = crear_aviso(db, crear_usuario(db, "ajeno@prueba.test"))
    crear_usuario(db, "intruso@prueba.test")
    ingresar(cliente, "intruso@prueba.test")
    assert cliente.get(f"/arrendador/inmuebles/{ajeno}").status_code == 403


def test_aviso_pendiente_no_es_publico(cliente, db):
    aviso = crear_aviso(db, crear_usuario(db, "pend@prueba.test"), estado="pendiente")
    evaluar(db, aviso)
    assert cliente.get(f"/inmuebles/{aviso}").status_code == 404
    assert cliente.get(f"/inmuebles/{aviso}/ficha.pdf").status_code == 404


def test_flujo_resena_verificada(cliente, db):
    aviso = crear_aviso(db, crear_usuario(db, "cod@prueba.test"))
    evaluar(db, aviso)
    db.execute("INSERT INTO codigos_visita(inmueble_id, codigo) VALUES (?, 'ABC123')", (aviso,))
    db.commit()
    crear_usuario(db, "resena@prueba.test", "estudiante")
    ingresar(cliente, "resena@prueba.test")
    csrf = token(cliente, f"/inmuebles/{aviso}")
    cliente.post(f"/estudiante/resena/{aviso}", data={"csrf_token": csrf, "puntaje": "5", "comentario": "Muy buen cuarto, tal como en las fotos.", "codigo": "abc123"})
    fila = db.execute("SELECT verificada FROM resenas").fetchone()
    assert fila["verificada"] == 1
    assert db.execute("SELECT usado_por FROM codigos_visita").fetchone()[0] is not None
    respuesta = cliente.post(f"/estudiante/resena/{aviso}", follow_redirects=True,
                             data={"csrf_token": csrf, "puntaje": "1", "comentario": "Intento de una segunda reseña aquí.", "codigo": ""})
    assert "Ya dejaste" in respuesta.get_data(as_text=True)


def test_codigo_de_visita_no_se_reutiliza(cliente, db):
    aviso = crear_aviso(db, crear_usuario(db, "cod2@prueba.test"))
    evaluar(db, aviso)
    usuario = crear_usuario(db, "usado@prueba.test", "estudiante")
    db.execute("INSERT INTO codigos_visita(inmueble_id, codigo, usado_por) VALUES (?, 'USADO1', ?)", (aviso, usuario))
    db.commit()
    crear_usuario(db, "nuevo@prueba.test", "estudiante")
    ingresar(cliente, "nuevo@prueba.test")
    csrf = token(cliente, f"/inmuebles/{aviso}")
    respuesta = cliente.post(f"/estudiante/resena/{aviso}", follow_redirects=True,
                             data={"csrf_token": csrf, "puntaje": "5", "comentario": "Reseña con un código ya utilizado.", "codigo": "USADO1"})
    assert "no es válido" in respuesta.get_data(as_text=True)


def test_flujo_reporte_moderacion_y_lista(cliente, app, db):
    dueno = crear_usuario(db, "reportado@prueba.test")
    aviso = crear_aviso(db, dueno)
    otro = crear_aviso(db, dueno, titulo="Otro cuarto del mismo número")
    for identificador in (aviso, otro):
        evaluar(db, identificador)
    crear_usuario(db, "victima@prueba.test", "estudiante")
    ingresar(cliente, "victima@prueba.test")
    csrf = token(cliente, f"/inmuebles/{aviso}")
    cliente.post(f"/estudiante/reportar/{aviso}", data={"csrf_token": csrf, "motivo": "cobro_indebido", "detalle": "Me pidieron un depósito y desaparecieron.", "monto_perdido": "300"})
    assert ReporteDAO(db).obtener(1)["estado"] == "abierto"
    pdf = cliente.get("/estudiante/reportes/1/expediente.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")

    otro_cliente = app.test_client()
    crear_usuario(db, "otra@prueba.test", "estudiante")
    ingresar(otro_cliente, "otra@prueba.test")
    assert otro_cliente.get("/estudiante/reportes/1/expediente.pdf").status_code == 403

    admin = app.test_client()
    crear_usuario(db, "admin@prueba.test", "admin")
    ingresar(admin, "admin@prueba.test")
    csrf = token(admin, "/admin/reportes")
    admin.post("/admin/reportes/1", data={"csrf_token": csrf, "estado": "confirmado", "resolucion": "Comprobado"})
    assert ListaContactosDAO(db).contiene("987654321")
    assert InmuebleDAO(db).obtener(aviso)["trust_score"] <= 24
    assert InmuebleDAO(db).obtener(otro)["nivel_riesgo"] == "Crítico"

    admin.post("/admin/reportes/1", data={"csrf_token": csrf, "estado": "descartado", "resolucion": "Rectificado"})
    assert not ListaContactosDAO(db).contiene("987654321")
    assert InmuebleDAO(db).obtener(otro)["trust_score"] > 24


def test_descargo_del_arrendador(cliente, db):
    dueno = crear_usuario(db, "descargo@prueba.test")
    aviso = crear_aviso(db, dueno)
    evaluar(db, aviso)
    estudiante = crear_usuario(db, "rep@prueba.test", "estudiante")
    ReporteDAO(db).insertar({"inmueble_id": aviso, "reportante_id": estudiante, "motivo": "otro", "detalle": "Detalle de prueba suficiente."})
    ingresar(cliente, "descargo@prueba.test")
    csrf = token(cliente, "/arrendador/")
    cliente.post("/arrendador/reportes/1/descargo", data={"csrf_token": csrf, "texto": "El inmueble existe y puede visitarse."})
    assert db.execute("SELECT COUNT(*) FROM descargos").fetchone()[0] == 1


def test_moderacion_de_documento_sube_puntaje(cliente, db):
    aviso = crear_aviso(db, crear_usuario(db, "doc@prueba.test"))
    antes = evaluar(db, aviso).trust_score
    DocumentoDAO(db).insertar({"inmueble_id": aviso, "tipo": "titularidad", "archivo": "t.pdf", "sha256": "abc"})
    crear_usuario(db, "mod@prueba.test", "admin")
    ingresar(cliente, "mod@prueba.test")
    csrf = token(cliente, "/admin/documentos")
    cliente.post("/admin/documentos/1", data={"csrf_token": csrf, "estado": "aprobado"})
    assert InmuebleDAO(db).obtener(aviso)["trust_score"] > antes


def test_admin_exporta_todos_los_formatos(cliente, db):
    aviso = crear_aviso(db, crear_usuario(db, "exp@prueba.test"))
    agregar_foto(db, aviso, foto(1))
    evaluar(db, aviso)
    crear_usuario(db, "adm@prueba.test", "admin")
    ingresar(cliente, "adm@prueba.test")
    assert cliente.get("/admin/exportar/distritos.pdf").data.startswith(b"%PDF")
    assert cliente.get("/admin/exportar/catalogo.xlsx").data.startswith(b"PK")
    assert b"severidad" in cliente.get("/admin/exportar/alertas.csv").data
    for ruta in ("/admin/", "/admin/avisos", "/admin/documentos", "/admin/reportes", "/admin/alertas", "/admin/redes",
                 "/admin/contactos-riesgo", "/admin/usuarios", "/admin/fuentes", "/admin/auditoria", "/api/admin/indicadores"):
        assert cliente.get(ruta).status_code == 200, ruta


def test_admin_no_puede_desactivarse(cliente, db):
    identificador = crear_usuario(db, "yo@prueba.test", "admin")
    ingresar(cliente, "yo@prueba.test")
    csrf = token(cliente, "/admin/usuarios")
    cliente.post(f"/admin/usuarios/{identificador}", data={"csrf_token": csrf, "campo": "activo", "valor": "0"})
    assert UsuarioDAO(db).obtener(identificador)["activo"] == 1


def test_verificador_web(cliente):
    csrf = token(cliente, "/verificador")
    respuesta = cliente.post("/verificador", data={"csrf_token": csrf, "texto": "Urgente, solo hoy, deposita y te envio las llaves por courier", "pide_pago_previo": "on"})
    html = respuesta.get_data(as_text=True)
    assert "Resultado del análisis" in html and "Te apuran" in html


def test_verificador_web_detecta_pago_urgente_en_aviso_de_cercado(cliente):
    csrf = token(cliente, "/verificador")
    respuesta = cliente.post("/verificador", data={
        "csrf_token": csrf,
        "texto": "cuarto en cercado a 200 soles yapea ya y no te quedes sin lugar donde vivir",
    })
    html = respuesta.get_data(as_text=True)
    assert "Riesgo alto" in html
    assert "Pide un pago inmediato" in html and "yapea ya" in html
    assert "Te apuran para decidir" in html
    assert "Visita el lugar y conoce al arrendador antes de pagar." in html


def test_verificador_web_no_muestra_un_porcentaje_de_seguridad(cliente):
    csrf = token(cliente, "/verificador")
    respuesta = cliente.post("/verificador", data={"csrf_token": csrf, "texto": "Cuarto con Wi-Fi."})
    html = respuesta.get_data(as_text=True)
    assert "Información insuficiente" in html
    assert "No se detectaron señales de riesgo en los datos ingresados." in html
    assert "Puntaje de seguridad" not in html and "puntaje-valor" not in html and "n-ok" not in html


def test_verificador_web_con_archivo_invalido(cliente):
    csrf = token(cliente, "/verificador")
    respuesta = cliente.post("/verificador", content_type="multipart/form-data",
                             data={"csrf_token": csrf, "texto": "Cuarto", "imagen": (io.BytesIO(b"x"), "a.jpg")})
    assert "No pudimos leer" in respuesta.get_data(as_text=True)


def test_contrato_analiza_y_genera(cliente):
    csrf = token(cliente, "/contrato")
    html = cliente.post("/contrato", data={"csrf_token": csrf, "accion": "analizar", "texto": "La garantia no sera devuelta al terminar el contrato de alquiler."}).get_data(as_text=True)
    assert "La garantía no se devuelve" in html
    pdf = cliente.post("/contrato", data={"csrf_token": csrf, "accion": "generar", "arrendador": "A <b>", "doc_arrendador": "1", "estudiante": "E",
                                          "doc_estudiante": "2", "direccion": "D", "ambiente": "C", "plazo_meses": "6", "inicio": "2026-11-01",
                                          "dia_pago": "5", "renta": "500", "garantia": "500", "dias_devolucion": "15", "servicios": "Agua", "aviso_dias": "30"})
    assert pdf.data.startswith(b"%PDF")


def test_contenido_de_usuario_se_escapa(cliente, db):
    aviso = crear_aviso(db, crear_usuario(db, "xss@prueba.test"), titulo="<script>alert(1)</script> cuarto")
    evaluar(db, aviso)
    assert "<script>alert(1)" not in cliente.get(f"/inmuebles/{aviso}").get_data(as_text=True)


def test_ruta_media_no_sale_de_la_carpeta(cliente):
    assert cliente.get("/media/../depaseguro.db").status_code == 404


def test_cabeceras_de_seguridad(cliente):
    cabeceras = cliente.get("/").headers
    assert cabeceras["X-Content-Type-Options"] == "nosniff" and cabeceras["X-Frame-Options"] == "SAMEORIGIN"

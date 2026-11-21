"""Llena la plantilla oficial del informe final con el contenido real del proyecto.

Uso:  python scripts/generar_informe.py RUTA_PLANTILLA.docx
"""
from __future__ import annotations

import copy
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402
from docx.table import Table  # noqa: E402
from docx.text.paragraph import Paragraph  # noqa: E402

from docx_util import Plantilla, agregar_campo, ajustar_filas, fijar_celda, fijar_parrafo, finalizar_con_word, run_con_pendientes  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DIAG, CAP, EVI = RAIZ / "docs" / "diagramas", RAIZ / "docs" / "capturas", RAIZ / "docs" / "evidencias"
SALIDA = RAIZ / "entregables" / "Informe_Final_DepaSeguro_AQP.docx"
TITULO = ("DepaSeguro AQP: Plataforma de Verificación de Autenticidad, Calificación de Inmuebles y Detección de "
          "Arriendos Fraudulentos para Estudiantes Universitarios")

bd = sqlite3.connect(RAIZ / "data" / "depaseguro.db")
bd.row_factory = sqlite3.Row
ANUAL = {f["anio"]: f["total"] for f in bd.execute(
    "SELECT anio, SUM(cantidad) total FROM denuncias_distrito WHERE modalidad='Estafa' GROUP BY anio")}
CIBER = [dict(f) for f in bd.execute(
    """SELECT anio, SUM(CASE WHEN delito LIKE 'Fraude%' THEN cantidad ELSE 0 END) fraude,
       SUM(CASE WHEN delito LIKE 'Suplantaci%' THEN cantidad ELSE 0 END) suplantacion FROM ciberdelitos GROUP BY anio""")]
CAMPUS = bd.execute("SELECT COUNT(*) FROM campus").fetchone()[0]
TABLAS = [f[0] for f in bd.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
fuentes = [dict(f) for f in bd.execute("SELECT * FROM fuentes_datos ORDER BY categoria DESC, nombre")]
n = lambda v: f"{v:,}".replace(",", " ")

RF = [
    ("RF001", "Gestión de cuentas y roles", "Ninguno", "Registrar e iniciar sesión como estudiante o arrendador. El administrador gestiona verificación y estado de cuentas. Las contraseñas se guardan como hash."),
    ("RF002", "Publicación de avisos", "RF001", "El arrendador registra, edita y retira avisos con tipo, ubicación, área, precio, moneda, periodo, servicios y condiciones."),
    ("RF003", "Análisis de imágenes", "RF002", "Validar cada imagen, calcular SHA-256 y hash perceptual dHash, y compararla con avisos de otros arrendadores."),
    ("RF004", "Documentos de titularidad", "RF002", "Cargar título, partida, recibo o identidad. Moderación aprueba o rechaza y el puntaje se recalcula."),
    ("RF005", "Normalización de precios", "RF002, RF013", "Convertir cada precio a soles por mes y por m². Usar el tipo de cambio venta del BCRP para avisos en dólares."),
    ("RF006", "Detección de patrones", "RF003, RF005", "Ejecutar ocho detectores y un motor lógico para reconocer precio anormal, foto clonada, contacto reincidente, adelanto fantasma, ubicación dudosa y condiciones abusivas."),
    ("RF007", "Cálculo del Trust Score", "RF006", "Calcular un índice de 0 a 100 con documentos, identidad, precio, fotos, contacto, condiciones y comunidad, y explicar cada componente."),
    ("RF008", "Búsqueda por cercanía", "RF007, RF013", "Filtrar avisos por campus, radio, distrito, tipo, precio y puntaje, y ordenarlos por compatibilidad."),
    ("RF009", "Verificación de aviso externo", "RF006", "Analizar texto, teléfono, precio y foto de un aviso visto fuera de la plataforma, sin publicarlo."),
    ("RF010", "Reseñas verificadas", "RF001", "Registrar reseñas. Una reseña queda verificada si incluye un código de visita válido y de un solo uso."),
    ("RF011", "Reportes y descargos", "RF001", "El estudiante reporta un aviso y el arrendador responde. Moderación confirma o descarta. Un caso confirmado agrega el teléfono a contactos de riesgo."),
    ("RF012", "Alertas automáticas", "RF007, RF013", "Generar alertas para moderación, favoritos que bajan de puntaje, búsquedas coincidentes y aumentos de estafas por distrito."),
    ("RF013", "Lectura automática de fuentes", "Ninguno", "Leer BCRP, MININTER, Ministerio Público, SUNEDU, OpenStreetMap, Wikidata y Transparency International cada 24 horas, registrar el resultado y conservar datos válidos si una fuente falla."),
    ("RF014", "Observatorio de zonas", "RF013", "Mostrar denuncias por distrito, tasa por 10 000 habitantes, serie mensual y proyección lineal."),
    ("RF015", "Reportes y exportación", "RF007, RF013", "Generar reportes PDF, Excel y CSV para ficha del inmueble, riesgo por distrito, catálogo y alertas."),
    ("RF016", "Revisión y modelo de contrato", "Ninguno", "Detectar cláusulas potencialmente abusivas y generar un contrato modelo en PDF."),
    ("RF017", "Expediente de apoyo", "RF011", "Generar un PDF con hechos, datos del aviso, huellas digitales y pasos para acudir a la autoridad."),
    ("RF018", "Redes de cuentas", "RF003", "Agrupar avisos de distintas cuentas unidos por teléfono, foto o documento mediante Union-Find."),
]
RNF = [
    ("RNF001", "Portabilidad", "Funcionar en Chrome o Edge actuales y en pantallas de escritorio y móvil."),
    ("RNF002", "Seguridad", "Usar hash de contraseñas, CSRF, control por rol, consultas parametrizadas, validación de archivos y límite de intentos de acceso."),
    ("RNF003", "Privacidad", "Guardar documentos fuera de la carpeta pública y permitir su apertura solo a moderación."),
    ("RNF004", "Disponibilidad de datos", "Si una fuente externa falla, seguir funcionando con los últimos datos válidos y mostrar el error en el panel."),
    ("RNF005", "Explicabilidad", "Mostrar por qué se obtuvo cada puntaje y evitar afirmaciones de culpabilidad."),
    ("RNF006", "Mantenibilidad", "Separar capas y mantener pruebas automáticas. La cobertura actual es 90 %."),
    ("RNF007", "Trazabilidad", "Registrar lecturas de fuentes, evaluaciones, acciones de moderación y exportaciones relevantes."),
]
CU = [
    ("CU01", "Buscar por campus", "Estudiante"), ("CU02", "Consultar Trust Score", "Estudiante"), ("CU03", "Verificar aviso externo", "Estudiante"),
    ("CU04", "Registrar reseña", "Estudiante"), ("CU05", "Reportar y descargar expediente", "Estudiante"), ("CU06", "Publicar aviso", "Arrendador"),
    ("CU07", "Cargar documentos", "Arrendador"), ("CU08", "Generar código de visita", "Arrendador"), ("CU09", "Presentar descargo", "Arrendador"),
    ("CU10", "Moderar avisos y documentos", "Moderador"), ("CU11", "Resolver reportes", "Moderador"), ("CU12", "Revisar redes de cuentas", "Moderador"),
    ("CU13", "Exportar reportes", "Moderador"), ("CU14", "Leer fuentes oficiales", "Planificador"), ("CU15", "Generar alertas", "Planificador"),
]
CU_DETALLE = [
    ("CU03 – Verificar aviso externo", "Estudiante", "Ninguna.", "1. Pega el texto.\n2. Agrega precio, teléfono o foto.\n3. Marca si piden pago, si no hay contrato o visita.\n4. El sistema analiza y consulta reglas.\n5. Muestra puntaje, señales y recomendación.", "Si la imagen no es válida, informa el error y permite corregirla.", "El análisis queda registrado sin publicar el aviso."),
    ("CU06 – Publicar aviso", "Arrendador", "Sesión iniciada como arrendador.", "1. Completa el formulario.\n2. Sube fotos.\n3. El sistema valida, normaliza y evalúa.\n4. El aviso queda pendiente.\n5. OpenStreetMap verifica la dirección en segundo plano.", "Si faltan datos, muestra el motivo y no guarda el aviso.", "Aviso pendiente con Trust Score inicial."),
    ("CU11 – Resolver reportes", "Moderador", "Existe un reporte.", "1. Revisa relato y descargo.\n2. Elige en revisión, confirmado o descartado.\n3. Si confirma, el teléfono pasa a contactos de riesgo.\n4. El sistema reevalúa los avisos relacionados.", "Si descarta, el aviso conserva su estado.", "Decisión registrada en auditoría y puntajes actualizados."),
    ("CU14 – Leer fuentes oficiales", "Planificador", "Pasaron 24 horas o el administrador ejecuta la lectura.", "1. Consulta cada fuente.\n2. Compara la huella.\n3. Transforma y guarda.\n4. Recalcula avisos.\n5. Genera alertas de zona.", "Si una fuente falla, registra el error y continúa con las demás.", "Datos, historial y puntajes actualizados."),
]
INTERFACES = [
    ("INTERFAZ001 – Inicio, tipo: Web", "01_inicio", "Presenta logo, menú, banner, indicadores, avisos destacados, video, blog, llamadas a la acción y pie de página.", 11),
    ("INTERFAZ002 – Búsqueda por campus, tipo: Web", "11_busqueda_campus", "Corresponde a CU01. Usa barra lateral de filtros y tarjetas con compatibilidad.", 13),
    ("INTERFAZ003 – Ficha de riesgo crítico, tipo: Web", "12_ficha_critica", "Corresponde a CU02. Explica puntaje, señales, patrones, recomendaciones y contexto de zona.", 10),
    ("INTERFAZ004 – Mapa, tipo: Web", "03_mapa", "Muestra avisos por nivel y locales universitarios sobre OpenStreetMap.", 14),
    ("INTERFAZ005 – Verificador, tipo: Web", "13_verificador_resultado", "Corresponde a CU03.", 12),
    ("INTERFAZ006 – Formulario de aviso, tipo: Web", "16_formulario_aviso", "Corresponde a CU06. Permite marcar la ubicación en el mapa.", 9),
    ("INTERFAZ007 – Panel de administración, tipo: Web", "18_panel_admin", "Corresponde a CU10 y CU13. Incluye indicadores, gráficos, exportaciones y alertas.", 10),
    ("INTERFAZ008 – Fuentes automáticas, tipo: Web", "21_admin_fuentes", "Corresponde a CU14. Muestra estado, registros e historial.", 12),
    ("INTERFAZ009 – Vista móvil, tipo: Móvil", "27_movil_ficha", "La misma aplicación se adapta a pantallas pequeñas.", 5.2),
]
DESCRIPCIONES = {
    "id": "Identificador único", "creado_en": "Fecha y hora de registro", "nombre": "Nombre descriptivo", "email": "Correo electrónico",
    "password_hash": "Hash de la contraseña", "rol": "Rol de la cuenta", "telefono": "Celular normalizado", "tipo_doc": "Tipo de documento",
    "num_doc": "Número de documento", "verificado": "Indica verificación", "activo": "Indica si puede ingresar", "es_demo": "Marca datos ficticios",
    "ubigeo": "Código de distrito del INEI", "lat": "Latitud", "lon": "Longitud", "poblacion": "Habitantes", "poblacion_fuente": "Origen de la población",
    "universidad": "Nombre de la universidad", "codigo_local": "Código de local de SUNEDU", "distrito": "Nombre del distrito", "licencia": "Estado de licenciamiento",
    "fecha_corte": "Fecha de corte de la fuente", "actualizado_en": "Fecha de última actualización", "arrendador_id": "Arrendador relacionado",
    "titulo": "Título", "descripcion": "Descripción", "tipo": "Clasificación", "direccion": "Dirección declarada", "area_m2": "Área en m²", "precio": "Precio publicado",
    "moneda": "PEN o USD", "periodo": "Periodo del precio", "precio_mensual_pen": "Precio normalizado mensual", "precio_m2_pen": "Precio normalizado por m²",
    "adelanto_meses": "Meses de adelanto", "garantia_meses": "Meses de garantía", "pago_previo_visita": "Pide pago antes de visitar", "contrato_escrito": "Ofrece contrato",
    "telefono_contacto": "Teléfono del aviso", "estado": "Estado del registro", "trust_score": "Índice de 0 a 100", "nivel_riesgo": "Nivel calculado",
    "direccion_estado": "Resultado de verificación", "inmueble_id": "Inmueble relacionado", "servicio_id": "Servicio relacionado", "archivo": "Nombre del archivo guardado",
    "sha256": "Huella criptográfica", "dhash": "Hash perceptual", "ancho": "Ancho en píxeles", "alto": "Alto en píxeles", "observacion": "Comentario de revisión",
    "revisado_por": "Moderador", "revisado_en": "Fecha de revisión", "codigo": "Código de un solo uso", "usado_por": "Estudiante que lo usó", "usado_en": "Fecha de uso",
    "estudiante_id": "Autor de la reseña", "puntaje": "Calificación", "comentario": "Experiencia", "verificada": "Reseña validada con código", "reportante_id": "Autor del reporte",
    "motivo": "Motivo", "detalle": "Detalle", "telefono_reportado": "Teléfono usado en el caso", "monto_perdido": "Monto declarado", "resolucion": "Decisión de moderación",
    "resuelto_en": "Fecha de resolución", "reporte_id": "Reporte relacionado", "texto": "Texto presentado", "nivel": "Nivel calculado", "componentes": "Componentes en JSON",
    "hallazgos": "Señales en JSON", "patrones": "Patrones en JSON", "usuario_id": "Usuario relacionado", "severidad": "Severidad", "mensaje": "Mensaje", "clave": "Clave única",
    "leida": "Indica lectura", "campus_id": "Campus elegido", "radio_km": "Radio en km", "precio_max": "Presupuesto", "trust_min": "Puntaje mínimo", "resultado": "Resultado en JSON",
    "entidad": "Entidad", "categoria": "Estado u ONG", "url": "Dirección de la fuente", "uso": "Uso en el sistema", "ultima_ejecucion": "Última lectura", "ultimo_exito": "Última lectura exitosa",
    "registros": "Cantidad procesada", "huella": "Huella de contenido", "fuente": "Fuente", "inicio": "Inicio", "fin": "Fin", "periodo_": "Periodo", "valor": "Valor", "anio": "Año", "mes": "Mes",
    "modalidad": "Modalidad", "cantidad": "Cantidad", "distrito_fiscal": "Distrito fiscal", "delito": "Delito", "consulta": "Consulta enviada", "slug": "Ruta amigable", "resumen": "Resumen",
    "contenido": "Contenido", "atendido": "Indica atención", "accion": "Acción", "entidad_id": "Registro afectado",
}


def caratula(pl: Plantilla) -> None:
    titulo = pl.parrafo(11)
    fijar_parrafo(titulo, f"Título: {TITULO}")
    titulo.runs[0].font.size = Pt(11)
    for indice in (0, 1, 12, 14, 15, 19):
        pl.cuerpo.remove(pl.els[indice])
    p = pl.parrafo(13)
    fijar_parrafo(p, "GitHub/GitLab: ")
    run_con_pendientes(p, "[COMPLETAR enlace del repositorio]")
    p = pl.parrafo(16)
    fijar_parrafo(p, "Ciclo: ")
    run_con_pendientes(p, "[COMPLETAR ciclo]")
    integrantes = pl.parrafo(17)
    integrantes.runs[-1].text = "Grupo 08"
    integrantes.runs[-1].font.color.rgb = RGBColor(0, 0, 0)
    for run in integrantes.runs[:-1]:
        if "[" in run.text or "Ordenado" in run.text or "Apellidos" in run.text or "]" in run.text:
            run.text = ""
    tabla = Table(pl.els[18], pl.doc)
    datos = [("1", "U23223248", "Cáceres Quispe", "Kasandra Coraly"), ("2", "U23259479", "Dolorier Arias", "Alisson"), ("3", "-", "-", "-")]
    for fila, valores in zip(tabla.rows[1:], datos):
        for celda, valor in zip(fila.cells, valores):
            fijar_celda(celda, valor)
    fijar_parrafo(pl.parrafo(22), "2026")


def indices(pl: Plantilla) -> None:
    for inicio, fin, tipo in ((30, 57, "Ilustración"), (60, 69, "Tabla")):
        pl.limpiar(inicio, fin)
        cursor = pl.en(inicio)
        parrafo = cursor._parrafo("Normal")
        agregar_campo(parrafo, f' TOC \\h \\z \\c "{tipo}" ', "Actualiza este índice en Word.")


def versiones(pl: Plantilla) -> None:
    tabla = Table(pl.els[75], pl.doc)
    filas = [("06-11-2026", "1.0", "Equipo", "Creación del documento con análisis, diseño, implementación y pruebas del prototipo.")]
    for fila, valores in zip(tabla.rows[1:], filas):
        for celda, valor in zip(fila.cells, list(valores) + ["", ""]):
            fijar_celda(celda, valor)
    for fila in tabla.rows[2:]:
        for celda in fila.cells:
            fijar_celda(celda, "")
    pl.limpiar(76, 79)


def resumen(pl: Plantilla) -> None:
    c = pl.en(82, 88)
    c.p("El proyecto aborda el mercado informal de cuartos y minidepartamentos que buscan los estudiantes universitarios en Arequipa, especialmente quienes llegan desde otras regiones. El dominio no corresponde a una empresa, sino a un escenario social donde participan estudiantes, arrendadores y entidades públicas.")
    c.p("Los principales problemas son los adelantos por inmuebles que podrían no existir, las fotos copiadas, las condiciones abusivas y la falta de información para comparar avisos. "
        f"Como contexto, las denuncias por estafa de todo tipo en la provincia de Arequipa pasaron de {n(ANUAL[2018])} en 2018 a {n(ANUAL[2024])} en 2024, según datos del MININTER.")
    c.p("La solución es una aplicación web con frontend en HTML, CSS y JavaScript, backend exclusivamente en Python con Flask y persistencia en SQLite. Python normaliza precios, compara imágenes, ejecuta reglas lógicas, calcula un Trust Score, genera alertas y reportes, y lee automáticamente siete fuentes del Estado y organizaciones sin fines de lucro.")
    c.p("Sus módulos principales son catálogo y búsqueda por campus, evaluación de riesgo, verificador de avisos externos, comunidad y reportes, contratos, observatorio de zonas, moderación y lectura automática de fuentes.")
    c = pl.en(91, 93, estilo="Normal")
    c.p("This project addresses the informal market of rooms and small apartments sought by university students in Arequipa, Peru. Students may face advance-payment scams, copied photographs and abusive rental conditions. "
        "DepaSeguro AQP is a web application with a Python and Flask backend and SQLite persistence. It normalizes prices, compares images with hashes, applies logic rules, calculates a Trust Score, creates alerts and reports, and automatically reads official and non-profit data sources. "
        "Its main modules are campus-based search, risk evaluation, external listing verification, community reports, contract review, zone analytics, moderation and data ingestion.")


def capitulo1(pl: Plantilla, vineta) -> None:
    c = pl.en(101, 105, vineta)
    c.p("Cada ciclo, estudiantes que se trasladan a Arequipa buscan vivienda cerca de sus campus. Gran parte de esta búsqueda ocurre en redes sociales, grupos de WhatsApp y carteles, donde la información no está estructurada ni verificada. Un estudiante recién llegado conoce poco la ciudad y puede sentir presión para reservar rápido.")
    c.p("Los actores son estudiantes, familias, arrendadores, moderadores de la plataforma y entidades que publican datos. El problema se presenta cuando se transfiere un adelanto sin visitar el inmueble, se usan fotos ajenas, un mismo contacto reaparece con distintos avisos o se ofrecen condiciones sin contrato.")
    c.tabla([["Indicador oficial", "Dato", "Fuente"],
             ["Estafas denunciadas en la provincia de Arequipa, 2018", n(ANUAL[2018]), "MININTER"],
             ["Estafas denunciadas en la provincia de Arequipa, 2024", n(ANUAL[2024]), "MININTER"],
             ["Estafas denunciadas en la provincia de Arequipa, 2025", n(ANUAL[2025]), "MININTER"],
             ["Estafas denunciadas de enero a septiembre de 2026", n(ANUAL[2026]), "MININTER"],
             ["Fraude informático en el distrito fiscal de Arequipa, 2019", n(CIBER[0]["fraude"]), "Ministerio Público"],
             ["Fraude informático de enero a septiembre de 2026", n(CIBER[-1]["fraude"]), "Ministerio Público"]],
            [10, 2.5, 4], "Indicadores de contexto obtenidos automáticamente.")
    c.p("Estos datos incluyen todo tipo de estafas y no miden solo alquileres. No se encontró una estadística oficial específica sobre estafas de vivienda estudiantil en Arequipa; por ello, la magnitud del problema local debe confirmarse con la encuesta del anexo.")
    for indice, texto in ((105, "Ser una referencia confiable para encontrar vivienda universitaria segura en Arequipa."),
                          (106, "Ayudar a estudiantes a decidir antes de pagar, con evaluaciones claras y datos verificables."),
                          (107, "Mercado de alquiler informal, avisos en redes sociales, transferencias digitales y datos públicos disponibles en portales del Estado."),
                          (108, "Dar visibilidad a arrendadores con documentos validados, combinar datos oficiales con reportes moderados y explicar cada resultado."),
                          (109, "Iniciar con un prototipo académico, validar con estudiantes de UTP y luego buscar alianzas con universidades y municipalidades.")):
        pl.en(indice, indice + 1).p(texto)
    c = pl.en(112, 117)
    c.p("Se modelaron tres procesos con notación BPMN: eventos de inicio y fin, tareas, compuertas exclusivas, flujos de secuencia y carriles por participante.")
    c.sub("BPM001 – Búsqueda actual de vivienda")
    c.imagen(DIAG / "bpmn_actual.png", "Diseño del proceso actual de búsqueda de vivienda.")
    c.sub("BPM002 – Publicación y verificación propuesta")
    c.imagen(DIAG / "bpmn_propuesto.png", "Diseño del proceso propuesto en DepaSeguro AQP.")
    c.sub("BPM003 – Lectura automática de fuentes")
    c.imagen(DIAG / "bpmn_ingesta.png", "Diseño del proceso de lectura automática.")
    c = pl.en(121, 134)
    c.p("La alternativa elegida es una plataforma web que evalúa avisos antes de que el estudiante entregue dinero. Fue aprobada por el docente como tema del Grupo 08, con la observación de ir más allá de registrar, calcular, alertar y reportar, y de leer datos de fuentes oficiales y ONG de forma automática.")
    c.p("El sistema cumple esa observación con estas capacidades de decisión:")
    c.vinetas(["Lee fuentes externas sin intervención humana y usa esos datos para recalcular precios, campus y contexto de zona.",
               "Deduce patrones de fraude con reglas lógicas, en lugar de limitarse a mostrar datos.",
               "Compara fotos mediante huellas perceptuales.",
               "Descubre redes de cuentas relacionadas.",
               "Analiza avisos externos, revisa contratos y prepara expedientes."])
    c.p("Tecnologías: Python, Flask, pandas, NumPy, Pillow, Requests, ReportLab, OpenPyXL, SQLite, Jinja2, Leaflet y Chart.js.")
    c.sub("MockUp001 – Verificador móvil")
    c.imagen(DIAG / "mockup_movil_verificador.png", "Mockup de vista móvil del verificador.", 6.5)
    c.sub("MockUp002 – Catálogo web")
    c.imagen(DIAG / "mockup_web_catalogo.png", "Mockup de vista web del catálogo.", 15)
    c.sub("MockUp003 – Ficha web")
    c.imagen(DIAG / "mockup_web_ficha.png", "Mockup de vista web de la ficha.", 15)
    c = pl.en(138, 141)
    c.p("Desarrollar una plataforma web que ayude a estudiantes universitarios de Arequipa a evaluar avisos de vivienda y reducir el riesgo de estafas, mediante análisis automático, datos oficiales y validación comunitaria.")
    c = pl.en(143, 148, vineta)
    c.vinetas(["Desarrollar un portal web para capturar inmuebles, buscar por cercanía a campus y registrar valoraciones.",
               "Programar en Python la detección de avisos duplicados, normalización de precios y cálculo del Trust Score.",
               "Diseñar la persistencia de inmuebles, credenciales, reportes y calificaciones.",
               "Leer automáticamente datos de cuatro entidades del Estado y tres fuentes de organizaciones sin fines de lucro.",
               "Generar alertas, reportes y herramientas de apoyo para decidir y actuar ante un posible fraude."])
    c = pl.en(152, 155, vineta)
    c.tabla([["Módulo", "Descripción"],
             ["Cuentas", "Registro, acceso y roles."], ["Catálogo", "Avisos, fotos, servicios, documentos, mapa y búsqueda por campus."],
             ["Riesgo", "Normalización, detectores, reglas lógicas, Trust Score e historial."], ["Comunidad", "Reseñas, códigos de visita, reportes y descargos."],
             ["Verificador", "Análisis de avisos vistos fuera de la plataforma."], ["Contratos", "Revisión de cláusulas y modelo PDF."],
             ["Observatorio", "Datos por distrito, ciberdelitos y proyección."], ["Moderación", "Avisos, documentos, reportes, usuarios, redes y auditoría."],
             ["Fuentes", "Lectura automática, planificador e historial."], ["Reportes", "PDF, Excel, CSV y expediente."]], [4, 12.5])
    c = pl.en(155, 158, vineta)
    c.vinetas(["Pagos, reservas o custodia de dinero.", "Envío real de correos, SMS o WhatsApp.", "Consulta automática de SUNARP, porque requiere validaciones del servicio.", "Reconocimiento visual de habitaciones con inteligencia artificial.", "Publicación en un servidor de producción."])
    c = pl.en(158, 161, vineta)
    c.vinetas(["No se encontró una fuente oficial de precios de alquiler por distrito; la mediana usa avisos registrados.",
               "Los avisos incluidos son datos ficticios de demostración.", "La detección de fotos solo compara imágenes dentro de la plataforma.",
               "Las denuncias son registros policiales, no delitos comprobados.", "La población distrital viene de Wikidata y no cubre todos los distritos.",
               "El IPC disponible en la API usada corresponde a Lima Metropolitana."])
    c = pl.en(161, 165)
    c.p("El proyecto es necesario porque el estudiante suele decidir con poca información y bajo presión. Una herramienta que explique las señales de riesgo puede evitar una transferencia equivocada. También ayuda a arrendadores honestos a demostrar confianza. Sin esta solución, cada estudiante seguiría verificando por su cuenta y los casos quedarían dispersos en chats y redes sociales.")
    c = pl.en(165, 169)
    c.p("El equipo está formado por dos integrantes. Los roles siguientes son una propuesta y deben confirmarse antes de entregar.")
    c.tabla([["Integrante", "Rol", "Responsabilidades"],
             ["Cáceres Quispe, Kasandra Coraly", "Líder del proyecto", "Coordina entregables, análisis, documentación y sustentación."],
             ["Dolorier Arias, Alisson", "Responsable de versiones", "Gestiona GitHub, integración, pruebas y demostración."]], [5.5, 4, 7])
    c.imagen(DIAG / "organigrama.png", "Organigrama del equipo.", 11)
    c = pl.en(169, 172)
    c.p("El presupuesto es una estimación referencial del equipo. Los montos deben ajustarse si se compran servicios adicionales.")
    c.tabla([["Recurso", "Detalle", "Costo estimado"],
             ["Hardware", "Computadoras personales existentes", "S/ 0"], ["Software", "Python, Flask, SQLite y librerías de código abierto", "S/ 0"],
             ["Datos", "Fuentes abiertas", "S/ 0"], ["Internet y electricidad", "Consumo durante el proyecto", "S/ 120"],
             ["Servidor futuro", "Servidor básico para piloto, por mes", "S/ 40"], ["Total del prototipo", "Sin horas de trabajo", "S/ 120"]], [4.5, 8.5, 3.5])
    c = pl.en(173, 176)
    c.p("El cronograma usa las semanas del curso. La estructura de trabajo se muestra en el WBS.")
    c.imagen(DIAG / "wbs.png", "Estructura de desglose del trabajo (WBS).")
    c.imagen(DIAG / "gantt.png", "Diagrama de Gantt del proyecto.")
    c = pl.en(176, 181)
    c.tabla([["Hito", "Entregable", "Semana", "Estado"],
             ["H1", "Tema aprobado por el docente", "12", "Cumplido"], ["H2", "Análisis, SRS y BPMN", "13", "Cumplido"], ["H3", "Diseño y mockups", "14", "Cumplido"],
             ["H4", "Prototipo con persistencia y fuentes", "15", "Cumplido"], ["H5", "Pruebas automatizadas", "16", "Cumplido"], ["H6", "Avance en GitHub", "17", "[COMPLETAR al subir el repositorio]"],
             ["H7", "Informe, manual y presentación", "18", "Borrador listo"], ["H8", "Sustentación", "18", "Pendiente"]], [1.5, 8, 2, 5], "Cronograma de hitos del proyecto.")


def capitulo2(pl: Plantilla) -> None:
    c = pl.en(186, 190)
    conceptos = [
        ("Programación funcional", "Trata el cálculo como aplicación de funciones. El proyecto usa funciones de orden superior, lambdas, composición, reducción y objetos inmutables en búsqueda y puntuación."),
        ("Programación lógica", "Representa conocimiento con hechos y reglas. El curso usó Prolog; el proyecto implementa en Python unificación, backtracking y negación por fallo para consultar reglas_fraude.pl."),
        ("Programación orientada a objetos", "Organiza el dominio con clases, herencia y polimorfismo. Usuario, Detector y FuenteDatos son clases abstractas con especializaciones."),
        ("Patrones de diseño", "Soluciones reutilizables descritas por Gamma et al. (1994). Se usan MVC, DAO, DTO, Factory, Strategy, Facade, Observer y Template Method."),
        ("Mediana y MAD", "Una estafa puede publicar precios extremos. Leys et al. (2013) recomiendan medidas robustas como la mediana y la desviación absoluta para detectar valores atípicos."),
        ("Hash perceptual", "SHA-256 detecta archivos idénticos. dHash compara diferencias de brillo y reconoce imágenes parecidas después de cambiar tamaño o compresión (Krawetz, 2013)."),
        ("Datos abiertos", "Permiten reutilizar información pública. El sistema consulta APIs y catálogos del Estado, además de datos de OpenStreetMap, Wikidata y Our World in Data."),
        ("BPMN y SRS", "BPMN modela procesos de negocio (Object Management Group, 2011). La especificación de requisitos sigue la lógica de IEEE 830 (IEEE, 1998)."),
        ("Marco legal", "El Código Penal regula la estafa en el artículo 196. La Ley 30096 trata los delitos informáticos y la Ley 29733 protege los datos personales. El sistema no reemplaza asesoría legal."),
    ]
    for titulo, texto in conceptos:
        c.sub(titulo)
        c.p(texto)


def capitulo3(pl: Plantilla) -> None:
    modelo_rf, modelo_rnf, modelo_dic = Table(pl.els[202], pl.doc), Table(pl.els[210], pl.doc), Table(pl.els[289], pl.doc)
    modelo_rf_xml, modelo_rnf_xml, modelo_dic_xml = (copy.deepcopy(modelo_rf._tbl), copy.deepcopy(modelo_rnf._tbl), copy.deepcopy(modelo_dic._tbl))
    modelo_rf, modelo_rnf, modelo_dic = Table(modelo_rf_xml, pl.doc), Table(modelo_rnf_xml, pl.doc), Table(modelo_dic_xml, pl.doc)

    c = pl.en(196, 204)
    c.p("Los requisitos se levantaron de la propuesta aprobada, los lineamientos del docente y el análisis del proceso actual.")
    for codigo, nombre, dependencias, descripcion in RF:
        c.sub(f"{codigo} – {nombre}")
        tabla = copy.deepcopy(modelo_rf_xml)
        c._colocar(tabla)
        t = Table(tabla, pl.doc)
        fijar_celda(t.rows[0].cells[0], codigo, 10)
        for fila, valor in zip(t.rows, [nombre, "1.0", "Grupo 08", "Propuesta aprobada y lineamientos", dependencias, descripcion, "Alta", "Implementado y probado", "Ninguno"]):
            fijar_celda(fila.cells[1], valor, 10)
        ajustar_filas(tabla)
        c.titulo_tabla("Tabla", f"{codigo} – {nombre}.")
    c = pl.en(205, 212)
    for codigo, nombre, descripcion in RNF:
        c.sub(f"{codigo} – {nombre}")
        tabla = copy.deepcopy(modelo_rnf_xml)
        c._colocar(tabla)
        t = Table(tabla, pl.doc)
        fijar_celda(t.rows[0].cells[0], codigo, 10)
        for fila, valor in zip(t.rows, [nombre, "1.0", "Grupo 08", "Lineamientos del curso", "Ninguno", descripcion, "Alta", "Implementado", "Ninguno"]):
            fijar_celda(fila.cells[1], valor, 10)
        ajustar_filas(tabla)
        c.titulo_tabla("Tabla", f"{codigo} – {nombre}.")
    pl.en(213, 216).p("Esta sección reúne el diseño funcional, visual, lógico y de datos del sistema.")
    c = pl.en(216, 228)
    c.imagen(DIAG / "casos_uso.png", "Casos de uso del sistema.")
    c.tabla([["Código", "Caso de uso", "Actor"]] + [list(x) for x in CU], [2, 10.5, 4], "Lista de casos de uso.")
    c.sub("Especificaciones de casos de uso")
    for nombre, actor, previa, flujo, alterno, final in CU_DETALLE:
        tabla = c.tabla([["Campo", "Descripción"], ["Caso de uso", nombre], ["Actor", actor], ["Precondición", previa], ["Flujo principal", flujo], ["Flujo alterno", alterno], ["Postcondición", final]],
                        [3.5, 13], f"Especificación – {nombre}.")
        ajustar_filas(tabla._tbl)
    c = pl.en(228, 246)
    c.p("Las interfaces se diseñaron primero como mockups y luego se implementaron. Las capturas provienen de la aplicación ejecutada en un navegador real con datos de demostración.")
    for titulo, archivo, texto, ancho in INTERFACES:
        c.sub(titulo)
        c.p(texto).paragraph_format.keep_with_next = True
        c.imagen(CAP / f"{archivo}.png", titulo.split(",")[0] + ".", ancho)
    pl.parrafo(248).paragraph_format.keep_with_next = True
    c = pl.en(248, 263)
    c.sub("Diseño de Reporte01 – Riesgo por distrito")
    c.imagen(DIAG / "mockup_reporte.png", "Diseño del reporte de riesgo por distrito.", 9)
    c.sub("Vista de Reporte01 – Riesgo por distrito")
    c.imagen(EVI / "reporte_distritos.png", "Reporte generado con ReportLab y datos reales del MININTER.", 12)
    c.sub("Vista de Reporte02 – Ficha de confiabilidad")
    c.imagen(EVI / "reporte_ficha.png", "Ficha de un aviso de demostración.", 11)
    c.sub("Vista de Reporte03 – Expediente de apoyo")
    c.imagen(EVI / "reporte_expediente.png", "Expediente de un caso ficticio.", 11)
    c = pl.en(263, 271)
    c.p("El diagrama muestra herencia en Usuario, Detector y FuenteDatos, y la separación entre evaluación, reglas y acceso a datos.")
    c.imagen(DIAG / "clases.png", "Diseño de clases.")
    c = pl.en(272, 279)
    c.p(f"La base contiene {len(TABLAS)} tablas. Inmuebles es la entidad central y se relaciona con imágenes, documentos, reseñas, reportes y evaluaciones.")
    c.imagen(DIAG / "entidad_relacion.png", "Modelo de entidad – relación.")
    c = pl.en(279, 285)
    c.p("El modelo físico usa SQLite. Las láminas se generaron leyendo las tablas reales de la base. PK indica clave primaria y FK clave foránea.")
    for numero in (1, 2, 3):
        c.imagen(DIAG / f"modelo_fisico_{numero}.png", f"Diseño físico de base de datos, lámina {numero}.", 15)
    c = pl.en(285, 293)
    c.p("Para SQLite, TEXT no define un tamaño fijo. En esos casos, el tamaño figura como variable.")
    for tabla_nombre in TABLAS:
        xml = copy.deepcopy(modelo_dic_xml)
        c._colocar(xml)
        t = Table(xml, pl.doc)
        fijar_celda(t.rows[0].cells[1], tabla_nombre.upper(), 9)
        prototipo = copy.deepcopy(t.rows[2]._tr)
        for fila in list(t.rows[2:]):
            xml.remove(fila._tr)
        columnas = bd.execute(f"PRAGMA table_info({tabla_nombre})").fetchall()
        foraneas = {f[3] for f in bd.execute(f"PRAGMA foreign_key_list({tabla_nombre})")}
        for columna in columnas:
            fila_xml = copy.deepcopy(prototipo)
            xml.append(fila_xml)
            fila = t.rows[-1]
            clave = "PK" if columna["pk"] else ("FK" if columna["name"] in foraneas else "")
            tipo = {"INTEGER": "Entero", "REAL": "Decimal", "TEXT": "Texto"}.get(columna["type"], columna["type"])
            valores = [clave, columna["name"].replace("_", " ").capitalize(), columna["name"], tipo, "Variable" if tipo == "Texto" else "8 bytes",
                       DESCRIPCIONES.get(columna["name"], columna["name"].replace("_", " ").capitalize())]
            for celda, valor in zip(fila.cells, valores):
                fijar_celda(celda, valor, 8)
        c.titulo_tabla("Tabla", f"Diccionario de datos - Entidad: {tabla_nombre}.")
    c = pl.en(293, 297)
    lineas = sum(1 for _ in (RAIZ / "database" / "schema.sql").open(encoding="utf-8"))
    c.p(f"El script completo está en database/schema.sql y tiene {lineas} líneas. Incluye tablas, restricciones CHECK, claves foráneas, índices y la vista v_inmuebles. Se adjunta en el paquete del proyecto.")
    c = pl.en(299, 305)
    c.p("La organización separa responsabilidades. models contiene el dominio, dao el acceso a datos, services las reglas de negocio, logic el razonamiento, ingestion las fuentes y web los controladores.")
    c.imagen(DIAG / "paquetes.png", "Organización de paquetes.", 14)
    c = pl.en(305, 312)
    c.tabla([["Librería", "Uso", "Motivo"],
             ["Flask", "Servidor web y rutas", "Es ligero y aplica fácilmente MVC."], ["pandas", "CSV, agrupación y estadística", "Se trabajó en el curso y procesa datos abiertos."],
             ["NumPy", "Tendencia lineal", "Permite calcular la proyección."], ["Pillow", "Validación y hash de imágenes", "Procesa imágenes sin servicios externos."],
             ["Requests", "Consulta de APIs", "Simplifica la lectura de fuentes."], ["ReportLab", "PDF", "Crea reportes desde Python."],
             ["OpenPyXL", "Excel", "Permite exportar hojas de cálculo."], ["pytest", "Pruebas", "Facilita TDD y cobertura."],
             ["Leaflet", "Mapas en frontend", "Usa OpenStreetMap."], ["Chart.js", "Gráficos en frontend", "Visualiza datos entregados por Python."]],
            [3, 6, 7.5], "Organización de librerías.")
    c.p("Conteo sin líneas vacías ni librerías externas: Python 4 801 líneas, de ellas 3 163 en la aplicación, 716 en pruebas y 922 en scripts. Plantillas, CSS y JavaScript suman 1 563 líneas. Python representa cerca de 72 % del total desarrollado, incluyendo SQL y reglas.")
    c = pl.en(312, 321)
    pl.limpiar(312, 321)
    modulos = [
        ("MÓDULO DAO.", "Patrón DAO: BaseDAO centraliza obtener, listar, insertar, actualizar y eliminar. Antes de insertar, conserva solo columnas reales y usa parámetros para evitar inyección SQL.", "codigo_dao", "Método de adición del DAO."),
        ("MÓDULO LÓGICO.", "Unificación: compara términos y crea enlaces de variables. BaseConocimiento la usa para resolver consultas sobre reglas_fraude.pl con backtracking.", "codigo_motor", "Unificación del motor lógico."),
        ("MÓDULO TRUST SCORE.", "Programación funcional: cada componente se calcula con una función pura. reduce suma los puntos y limitar mantiene el resultado entre 0 y 100.", "codigo_score", "Cálculo del Trust Score."),
        ("MÓDULO DE IMÁGENES.", "dHash reduce la foto, compara píxeles vecinos y crea una huella. La distancia de Hamming mide cuánto se parecen dos huellas.", "codigo_hash", "Hash perceptual de imágenes."),
        ("MÓDULO DE FUENTES.", "Template Method: ejecutar fija el proceso común. Cada fuente implementa obtener y cargar. Si falla, registra el error y conserva lo último leído.", "codigo_fuente", "Proceso común de lectura de fuentes."),
        ("MÓDULO DE BÚSQUEDA.", "Pipeline funcional: agrega distancias, filtra, calcula compatibilidad y ordena sin modificar los avisos originales.", "codigo_busqueda", "Pipeline de búsqueda."),
    ]
    for titulo, texto, imagen, leyenda in modulos:
        c.sub(titulo)
        c.p(texto).paragraph_format.keep_with_next = True
        c.imagen(EVI / f"{imagen}.png", leyenda, 15.5)
    c.p("La documentación técnica de 33 módulos se generó con Pydoc y está en docs/pydoc.")
    pl.en(321, 324).p("El sistema usa una arquitectura web por capas con MVC, integrada con un proceso independiente de ingesta.")
    c = pl.en(324, 328)
    c.tabla([["Elemento", "Aplicación", "Ubicación"],
             ["MVC", "Plantillas como vistas, Blueprints como controladores y servicios como modelo de negocio", "templates, web, services"],
             ["DAO", "Encapsula SQL por entidad", "dao/repositorios.py"], ["DTO", "Transporta resultados inmutables", "models/entidades.py"],
             ["Factory", "Crea el tipo correcto de usuario", "fabrica_usuario"], ["Strategy", "Un detector por aspecto", "services/detectores.py"],
             ["Facade", "Oculta el proceso de evaluación", "EvaluadorInmueble"], ["Observer", "Evaluación publica eventos y alertas se suscriben", "services/eventos.py"],
             ["Template Method", "Proceso común de fuentes", "FuenteDatos.ejecutar"],
             ["TDD", "Pruebas por requisitos e incidencias", "tests/"], ["SOLID", "Clases pequeñas, extensión por nuevas estrategias y dependencia de abstracciones", "Detector y FuenteDatos"]],
            [3, 9, 4.5], "Patrones y principios aplicados.")
    c = pl.en(328, 336)
    c.p("La vista llama a controladores Flask. Estos usan servicios Python y los servicios acceden a datos mediante DAO. El planificador alimenta la misma base y dispara nuevos cálculos.")
    c.imagen(DIAG / "arquitectura.png", "Arquitectura del sistema DepaSeguro AQP.")
    pl.en(338, 342).p("El proyecto usa Git de forma local y queda preparado para subir a GitHub. La carátula conserva un espacio para el enlace.")
    c = pl.en(342, 355)
    c.p("Se aplicó una estrategia con rama main para versiones estables, develop para integración y feature/* para cada componente. Las correcciones futuras pueden usar fix/*.")
    c.imagen(DIAG / "ramas_flujo.png", "Flujograma de ramificación.")
    c.imagen(EVI / "git_grafo.png", "Esquema de ramificación del proyecto.", 15.5)
    c.imagen(EVI / "git_ramas.png", "Listado de ramificación del proyecto.", 9)
    c = pl.en(355, 372)
    c.p("Cada rama feature se fusiona en develop con merge --no-ff para conservar la historia de integración. En GitHub se recomienda crear un Pull Request hacia develop, pedir revisión de la otra integrante y fusionar solo si pasan las pruebas.")
    c.vinetas(["Crear rama desde develop: git switch -c feature/nombre develop.", "Hacer cambios y ejecutar python -m pytest.", "Fusionar en develop después de la revisión.", "Fusionar develop en main para una versión estable."])
    c.p("No se presentaron conflictos porque cada rama agrupó archivos distintos.")
    c = pl.en(372, 386)
    c.p("Los commits siguen el formato tipo(alcance): descripción. Por ejemplo, feat(fuentes), test y docs.")
    c.imagen(EVI / "git_commit.png", "Aplicación de commit de cambio.", 15.5)
    c = pl.en(386, 407)
    c.p("Estas incidencias ocurrieron durante el desarrollo. Están registradas en docs/ISSUES.md y deben copiarse a GitHub Issues cuando se publique el repositorio.")
    c.tabla([["ID", "Incidencia", "Solución", "Prevención"],
             ["01", "Ubigeos incorrectos en dos distritos", "Comparación con dataset MININTER", "Validar catálogos con la fuente"],
             ["02", "El archivo 2020 del Ministerio Público incluía todos los delitos", "Filtrar por Ley 30096", "Prueba con datos ajenos"],
             ["03", "El dueño original perdía puntos cuando le copiaban fotos", "Penalizar solo a la copia posterior", "Prueba automática"],
             ["04", "Quince pruebas fallaron por estado compartido", "Limpiar el estado entre pruebas", "Fixtures independientes"],
             ["05", "Rutas de Windows demasiado largas", "Nombres más cortos", "Instalar en una ruta corta"],
             ["06", "Macros Jinja sin variables globales", "Registrar variables globales", "Prueba de páginas"]], [1, 6, 5, 4.5], "Incidencias y cambios realizados.")
    c.imagen(EVI / "pruebas.png", "Resultado de pruebas automáticas.", 15.5)
    c.p("[COMPLETAR capturas de Pull Requests e Issues después de subir el proyecto a GitHub]")


def cierre(pl: Plantilla) -> None:
    c = pl.en(411, 415)
    c.p("Se desarrolló un prototipo web funcional para evaluar avisos de vivienda universitaria, con frontend, backend Python y persistencia SQLite integrados.")
    c.p("Se implementó en Python la normalización de precios, la detección de fotos repetidas, las reglas de fraude y el Trust Score explicable.")
    c.p("La persistencia almacena inmuebles, usuarios, reportes, calificaciones, evaluaciones, alertas y datos externos en 27 tablas con restricciones.")
    c.p("Se atendió la observación del docente: el sistema lee automáticamente cuatro fuentes del Estado y tres fuentes de organizaciones sin fines de lucro, y usa esos datos en decisiones y alertas.")
    c.p("Las 124 pruebas automatizadas pasaron, con 90 % de cobertura. También se recorrió la aplicación en Chrome sin errores de interfaz.")
    c.p("El impacto real aún no se ha medido con usuarios. Para hacerlo, se necesita aplicar la encuesta y realizar un piloto.")
    c = pl.en(415, 420)
    c.p("Aplicar la encuesta del anexo para medir la frecuencia local de estas estafas.")
    c.p("Solicitar información a universidades y municipalidades para ampliar los precios de referencia.")
    c.p("Agregar notificaciones por correo o WhatsApp, y evaluar la consulta registral con autorización del usuario.")
    c.p("Publicar un piloto en un servidor seguro y revisar el cumplimiento de la Ley 29733 antes de usar datos reales.")
    c.p("Comparar imágenes con servicios externos autorizados para detectar fotos copiadas de internet.")
    c = pl.en(422, 434)
    referencias = [
        "Banco Central de Reserva del Perú. (2026). BCRPData: Series estadísticas. https://estadisticas.bcrp.gob.pe/estadisticas/series/",
        "Congreso de la República del Perú. (2011). Ley N.º 29733, Ley de Protección de Datos Personales.",
        "Congreso de la República del Perú. (2013). Ley N.º 30096, Ley de Delitos Informáticos.",
        "Gamma, E., Helm, R., Johnson, R., & Vlissides, J. (1994). Design patterns: Elements of reusable object-oriented software. Addison-Wesley.",
        "IEEE. (1998). IEEE Recommended Practice for Software Requirements Specifications (IEEE Std 830-1998).",
        "Krawetz, N. (2013). Kind of like that. The Hacker Factor Blog. https://www.hackerfactor.com/blog/?/archives/529-Kind-of-Like-That.html",
        "Leys, C., Ley, C., Klein, O., Bernard, P., & Licata, L. (2013). Detecting outliers: Do not use standard deviation around the mean, use absolute deviation around the median. Journal of Experimental Social Psychology, 49(4), 764-766.",
        "Martín Villalba, C. (s. f.). Lenguajes de programación. UNED.",
        "Ministerio del Interior. (2026). Denuncias policiales registradas a nivel nacional [Conjunto de datos]. Plataforma Nacional de Datos Abiertos. https://www.datosabiertos.gob.pe/dataset/denuncias-policiales-registradas-nivel-nacional-mininter",
        "Ministerio Público. (2026). Delitos informáticos denunciados ante el Ministerio Público [Conjunto de datos]. Plataforma Nacional de Datos Abiertos. https://www.datosabiertos.gob.pe/",
        "Object Management Group. (2011). Business Process Model and Notation (BPMN), Version 2.0. https://www.omg.org/spec/BPMN/2.0/",
        "OpenStreetMap contributors. (2026). OpenStreetMap y Nominatim. https://www.openstreetmap.org/",
        "Our World in Data. (2026). Corruption Perceptions Index, con datos de Transparency International. https://ourworldindata.org/grapher/ti-corruption-perception-index",
        "Pallets. (2026). Flask documentation. https://flask.palletsprojects.com/",
        "pandas development team. (2026). pandas documentation. https://pandas.pydata.org/docs/",
        "Superintendencia Nacional de Educación Superior Universitaria. (2026). SUNEDU - Programas académicos [Conjunto de datos]. Plataforma Nacional de Datos Abiertos. https://www.datosabiertos.gob.pe/",
        "Wikidata. (2026). Wikidata Query Service. https://query.wikidata.org/",
    ]
    for referencia in referencias:
        p = c.p(referencia)
        p.paragraph_format.left_indent = Pt(24)
        p.paragraph_format.first_line_indent = Pt(-24)


def anexos(pl: Plantilla) -> None:
    c = pl.en(436, 437)
    c.sub("Anexo A. Fuentes leídas automáticamente")
    c.tabla([["Fuente", "Tipo", "Registros", "Uso"]] + [[f["nombre"], "Estado" if f["categoria"] == "estado" else "ONG", f["registros"], f["uso"]] for f in fuentes], [5.5, 1.5, 2, 7.5], "Fuentes automáticas.")
    c.sub("Anexo B. Cumplimiento de partes web")
    c.tabla([["Parte solicitada", "Implementación"],
             ["Logo, encabezados y menú", "Plantilla base"], ["Botones y controles", "Formularios, filtros y acciones"], ["Redes sociales", "Compartir en WhatsApp, Facebook y X"],
             ["Imágenes, video y banner", "Inicio y fichas"], ["Barras laterales", "Catálogo, ficha y administración"], ["Contenido destacado", "Avisos destacados"],
             ["Pie, inicio y CTA", "Todas las páginas e inicio"], ["Blog", "Guías para estudiantes"], ["Formularios y contacto", "Registro, avisos, verificador y contacto"], ["Enlaces internos y externos", "Menú y pie de página"]], [7, 9.5], "Partes mínimas de la página web.")
    c.sub("Anexo C. Evidencia en la sociedad")
    c.p("[COMPLETAR con fotos, entrevistas o resultados reales de aplicación con estudiantes]")
    encuesta = pl.parrafo(439)
    encuesta.paragraph_format.left_indent = Cm(0)
    encuesta.paragraph_format.right_indent = Cm(0)
    encuesta.paragraph_format.first_line_indent = Cm(0)
    c = pl.en(439, 443)
    c.p("Instrumento propuesto para validar el problema. Aún no contiene respuestas.")
    c.tabla([["N.º", "Pregunta", "Respuesta"],
             ["1", "¿Vienes de otra provincia o región?", "Sí / No"], ["2", "¿Buscaste vivienda en Arequipa en el último año?", "Sí / No"],
             ["3", "¿Dónde encontraste avisos?", "Redes / WhatsApp / Carteles / Otro"], ["4", "¿Te pidieron dinero antes de visitar?", "Sí / No"],
             ["5", "¿Sufriste o conoces un caso de estafa?", "Sí / No"], ["6", "¿Cuánto dinero se perdió?", "Monto"], ["7", "¿Firmaste contrato?", "Sí / No"],
             ["8", "¿Usarías un verificador antes de pagar?", "Escala 1 a 5"], ["9", "¿Qué información te daría más confianza?", "Abierta"]], [1.2, 10.3, 5])
    c.p("[COMPLETAR resultados después de aplicar la encuesta]")


def main() -> None:
    pl = Plantilla(Path(sys.argv[1]))
    vineta = copy.deepcopy(pl.els[84].xpath("./w:pPr/w:numPr")[0])
    caratula(pl)
    indices(pl)
    versiones(pl)
    resumen(pl)
    capitulo1(pl, vineta)
    capitulo2(pl)
    capitulo3(pl)
    cierre(pl)
    anexos(pl)
    pl.quitar_imagenes_sin_uso()
    SALIDA.parent.mkdir(exist_ok=True)
    pl.doc.save(SALIDA)
    print(finalizar_con_word(SALIDA))


if __name__ == "__main__":
    main()

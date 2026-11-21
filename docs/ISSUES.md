# Incidencias reales del desarrollo

Registra estas incidencias como Issues cuando el repositorio esté en GitHub.

| ID | Incidencia | Causa | Solución | Prevención |
| --- | --- | --- | --- | --- |
| ISSUE-01 | Sabandía y Sachaca tenían ubigeo incorrecto | Códigos escritos de memoria | Se compararon con el dataset del MININTER | Validar catálogos con la fuente oficial |
| ISSUE-02 | 2020 mostraba 33 909 delitos informáticos en Arequipa | El CSV de ese año trae todos los delitos | Filtrar por Ley 30096 | Prueba con delitos ajenos a la ley |
| ISSUE-03 | El dueño original perdía puntos cuando le copiaban una foto | La comparación no consideraba quién publicó primero | Penalizar solo la copia posterior | Prueba `test_foto_copiada_penaliza_al_ultimo_no_al_original` |
| ISSUE-04 | Quince pruebas fallaron en cadena | El límite de intentos de acceso quedaba en memoria entre pruebas | Limpiar el estado en cada prueba | Fixtures independientes |
| ISSUE-05 | Windows no creaba archivos en rutas largas | Rutas de más de 260 caracteres | Nombres de archivo más cortos | Instalar el proyecto en una ruta corta |
| ISSUE-06 | Plantillas no reconocían `TIPOS` dentro de macros | Las macros de Jinja no reciben el contexto | Registrar `TIPOS` y `MOTIVOS` como globales | Prueba de todas las páginas |

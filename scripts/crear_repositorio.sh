#!/usr/bin/env bash
# Crea el historial Git por componentes, con ramas main, develop y feature/*.
set -e
TRAILER="Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
if [ -e .git ] || git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf '%s\n' 'La carpeta ya pertenece a un repositorio. Usa una copia sin historial.'
  exit 1
fi
git init -q -b main
git config user.name "Grupo 08 DepaSeguro AQP"
git config user.email "grupo08.depaseguro@example.com"
git config core.longpaths true

commit() { git commit -q -m "$1" -m "$TRAILER"; }
rama() {
  git switch -q -c "$1" develop
  shift
}
fusionar() {
  git switch -q develop
  git merge -q --no-ff "$1" -m "Merge $1 en develop" -m "$TRAILER"
}

git add .gitignore README.md INICIO_RAPIDO.md requirements.txt requirements-docs.txt pytest.ini
commit "chore: estructura inicial del proyecto"
git switch -q -c develop

rama feature/persistencia
git add database depaseguro/config.py depaseguro/dao depaseguro/models
commit "feat(bd): modelo físico, entidades y patrón DAO"
fusionar feature/persistencia

rama feature/logica-funcional
git add depaseguro/logic depaseguro/functional
commit "feat(logica): motor tipo Prolog y utilidades funcionales"
fusionar feature/logica-funcional

rama feature/motor-riesgo
git add depaseguro/services
commit "feat(riesgo): detectores, Trust Score, alertas y reportes"
fusionar feature/motor-riesgo

rama feature/fuentes-oficiales
git add depaseguro/ingestion
commit "feat(fuentes): lectura automática del Estado y ONG"
fusionar feature/fuentes-oficiales

rama feature/frontend
git add depaseguro/__init__.py depaseguro/web depaseguro/templates depaseguro/static run.py
commit "feat(web): portal, paneles y controladores Flask"
fusionar feature/frontend

rama feature/pruebas
git add tests
commit "test: pruebas unitarias y de integración"
fusionar feature/pruebas

rama feature/documentacion
git add scripts docs
commit "docs: diagramas, capturas, incidencias y scripts de apoyo"
fusionar feature/documentacion

git switch -q main
git merge -q --ff-only develop
git branch --list

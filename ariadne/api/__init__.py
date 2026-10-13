"""Flask blueprints. Each module is thin: parse the request, call a service,
return JSON. Behaviour belongs in ariadne/services."""

from ariadne.api import auth, export, images, library, projects, shell, tags

ALL = [shell.bp, library.bp, images.bp, tags.bp, export.bp, projects.bp, auth.bp]

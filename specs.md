Sí. Y de hecho no lo implementaría en PowerShell.

PowerShell puede ser el backend que habla con Outlook, pero el servidor MCP lo haría en Python.

Arquitectura recomendada
┌─────────────────────────┐
│ Claude Desktop          │
│ ChatGPT (MCP futuro)    │
│ VSCode Agent            │
│ Copilot Studio (custom) │
└────────────┬────────────┘
             │ MCP
             ▼
┌─────────────────────────┐
│ Productivity MCP Server │
│ Python                  │
└────────────┬────────────┘
             │
     ┌───────┼────────┬─────────┬─────────┐
     ▼       ▼        ▼         ▼
 Outlook   ToDo    OneNote   Planner
 COM       Graph    Graph     Graph


Objetivo

Que puedas escribir:

Muéstrame mis notas del bloque Tareas del lunes.


y el modelo ejecute:

{
  "tool": "calendar_get_event_body",
  "date": "2026-07-27",
  "subject": "Tareas"
}


devolviendo:

Política ADN
Marco IA Responsable
...

Stack tecnológico
Servidor MCP

Python 3.12

Framework:

pip install mcp


o

pip install fastmcp


Yo usaría:

FastMCP


porque simplifica mucho el desarrollo.

Herramientas MCP
1. Calendar
calendar_search

Entrada

{
  "from":"2026-07-27T00:00:00",
  "to":"2026-07-27T23:59:59",
  "subject":"Tareas"
}


Salida

[
  {
    "entryId":"ABC123",
    "subject":"Tareas (...)",
    "start":"...",
    "end":"..."
  }
]

calendar_get_event
{
  "entryId":"ABC123"
}


Salida

{
  "subject":"Tareas (...)",
  "body":"Política ADN..."
}

calendar_get_notes

Atajo:

{
  "date":"2026-07-27",
  "subject":"Tareas"
}

OneNote
onenote_search
{
  "query":"CESCE"
}

onenote_get_page
{
  "pageId":"123"
}

ToDo
todo_list
{
  "list":"Tasks"
}

todo_open_tasks
{}

Outlook backend

Aquí sí usaría COM.

Motivo

COM ve exactamente lo mismo que Outlook.

No dependes de:

Azure
App registrations
Consentimientos
Graph

Código conceptual:

import win32com.client

outlook = win32com.client.Dispatch("Outlook.Application")
ns = outlook.GetNamespace("MAPI")

calendar = ns.GetDefaultFolder(9)

for item in calendar.Items:
    print(item.Subject)
    print(item.Body)

Seguridad

MCP local.

localhost solamente


Sin puertos externos.

127.0.0.1


Sin autenticación inicial.

Porque:

si alguien entra en tu sesión Windows
ya está comprometido todo Outlook

Estructura de proyecto
productivity-mcp/
│
├── server.py
│
├── tools/
│   ├── calendar.py
│   ├── todo.py
│   ├── onenote.py
│   └── outlook.py
│
├── models/
│   └── schemas.py
│
└── config/
    └── settings.yaml

Fases
MVP (1 tarde)

Sólo Outlook.

Herramientas:

calendar_search
calendar_get_event
calendar_get_notes


Backend:

Outlook COM

V2

Añadir:

ToDo
OneNote


mediante Graph.

V3

Añadir:

Teams
SharePoint
Planner
Email search

Mi recomendación

Para tu problema concreto no haría Graph inicialmente.

Haría:

FastMCP
    +
Python
    +
Outlook COM


Todo en tu portátil.

Es la solución con mejor relación esfuerzo/resultado y te permitiría acceder exactamente a esos bloques tipo:

Tareas (...)
Reflexiones
Estrategia
Pendientes


que Outlook guarda como citas personales con texto en el cuerpo.

# 🛠️ Guía de Setup — Paper Radar

Tiempo estimado: **10–15 minutos**

---

## Paso 1: Crear el repositorio en GitHub

1. Ve a **https://github.com/new**
2. Nombre del repo: `paper-radar` (o el que prefieras)
3. Visibilidad: **Private** (recomendado — son tus reportes personales)
4. Marca ✅ "Add a README file"
5. Haz clic en **Create repository**

---

## Paso 2: Subir los archivos del proyecto

Tienes dos opciones:

### Opción A — GitHub Web (más fácil, sin Git)

1. En tu repo, haz clic en **"uploading an existing file"**
2. Sube los archivos respetando esta estructura:
   ```
   paper-radar/
   ├── .github/
   │   └── workflows/
   │       └── daily_papers.yml
   ├── scripts/
   │   └── fetch_papers.py
   ├── reports/
   │   └── README.md
   └── README.md
   ```
   > ⚠️ Para crear carpetas en GitHub web: en el nombre del archivo escribe `scripts/fetch_papers.py` y automáticamente crea la carpeta.

### Opción B — Git desde terminal

```bash
# Clona el repo vacío
git clone https://github.com/TU_USUARIO/paper-radar.git
cd paper-radar

# Copia los archivos descargados aquí
# Luego:
git add .
git commit -m "🚀 Initial setup"
git push origin main
```

---

## Paso 3: Habilitar GitHub Actions

1. En tu repo, ve a la pestaña **Actions**
2. Si te aparece un mensaje de confirmación, haz clic en **"I understand my workflows, go ahead and enable them"**
3. Verás el workflow `Paper Radar — Daily Report` en la lista

---

## Paso 4: Verificar que funciona (prueba manual)

1. Ve a **Actions** → `Paper Radar — Daily Report`
2. Haz clic en **"Run workflow"** → **"Run workflow"** (botón verde)
3. Espera ~2-3 minutos
4. Si el workflow queda en ✅ verde: **¡listo!**
5. Ve a `reports/` en tu repo y verás los primeros reportes

---

## Paso 5: Leer los reportes diariamente

**Opción A — Directamente en GitHub** (sin instalar nada):
- Abre `https://github.com/TU_USUARIO/paper-radar/tree/main/reports`
- Haz clic en el reporte del día y GitHub renderiza el Markdown

**Opción B — Clonar localmente** (leer sin internet):
```bash
git clone https://github.com/TU_USUARIO/paper-radar.git
cd paper-radar/reports
# Cada mañana:
git pull
# Abre el archivo .md con tu editor (VS Code, Obsidian, Typora, etc.)
```

**Opción C — Obsidian** (la más cómoda para leer):
1. Clona el repo en una carpeta local
2. Abre esa carpeta como Vault en Obsidian
3. Cada mañana: `git pull` y lees en Obsidian con renderizado bonito

---

## Personalización

Edita `scripts/fetch_papers.py` en la sección `CONFIGURATION`:

### Cambiar tus temas de interés (reporte filtrado)
```python
PERSONAL_TOPICS = [
    "cybersecurity", "information security", "vulnerability",
    "large language models", "LLM",
    "fintech", "fraud detection",
    # Agrega los tuyos aquí
]
```

### Cambiar categorías de arXiv
Busca categorías en https://arxiv.org/category_taxonomy
```python
ARXIV_CATEGORIES = [
    "cs.CR",   # Cryptography and Security ← ya incluido
    "cs.AI",   # Artificial Intelligence   ← ya incluido
    "q-fin.RM", # Risk Management (finanzas)
    # Agrega las que quieras
]
```

### Ajustar umbral de selección
```python
MIN_SCORE_GENERAL  = 30   # más bajo = más papers (menos filtrado)
MIN_SCORE_FILTERED = 45   # más alto = más estricto
```

---

## Estructura de un reporte

Cada reporte incluye por paper:
- **Score** (0-100) y barra visual
- **Por qué es relevante** (razones específicas del score)
- **Autores** y fecha
- **Links** directos al paper y PDF
- **Resumen** del abstract (primeras ~80 palabras)

Para profundizar en un paper: haz clic en el link al PDF o a arXiv/Semantic Scholar.

---

## Troubleshooting

**El workflow falla con error de permisos:**
- Ve a `Settings` → `Actions` → `General` → `Workflow permissions`
- Selecciona "Read and write permissions"

**No aparecen papers:**
- Verifica la pestaña Actions y revisa los logs del step "Generate paper reports"
- Es normal que algunos días haya menos papers si las fuentes tienen mantenimiento

**Quiero recibir el reporte por email (ya está integrado):**

El workflow ya incluye un paso que te envía el **reporte filtrado** por correo cada
mañana (con el general adjunto), usando `scripts/send_email.py` (solo stdlib).
Solo tienes que configurar las credenciales SMTP como **secrets** del repo:

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`:

| Secret | Valor | Ejemplo |
|--------|-------|---------|
| `SMTP_HOST` | servidor SMTP | `smtp.gmail.com` |
| `SMTP_PORT` | puerto | `465` (SSL) o `587` (STARTTLS) |
| `SMTP_USER` | cuenta que autentica | tu correo Gmail |
| `SMTP_PASS` | **App Password** (no tu contraseña normal) | ver abajo |
| `MAIL_FROM` | remitente (opcional) | tu correo |
| `MAIL_TO` | destinatario(s), separados por coma | tu correo |

> **Gmail:** activa 2FA y genera un *App Password* en
> https://myaccount.google.com/apppasswords — usa esos 16 caracteres en `SMTP_PASS`.

Si no configuras los secrets, el envío simplemente se omite (no rompe el workflow).

---

*Paper Radar — setup guide*

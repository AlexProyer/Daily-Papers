# 📡 Paper Radar

> Sistema automatizado de inteligencia de investigación científica.  
> Genera reportes diarios de los papers más relevantes de las principales fuentes académicas.

## Fuentes monitoreadas

| Fuente | API | Criterio de selección |
|--------|-----|-----------------------|
| **arXiv** | API pública | Papers de las últimas 24-48h en categorías configuradas |
| **Semantic Scholar** | API pública | Papers recientes con citas emergentes |
| **Papers With Code** | API pública | Papers con código público disponible |
| **HuggingFace Daily Papers** | API pública | Papers curados por la comunidad HF |

## Cómo funciona

1. **GitHub Actions** ejecuta el script todos los días a las **7:00 AM hora Colombia**
2. El script consulta las 4 APIs y filtra solo papers de las últimas 24-48 horas
3. Cada paper se evalúa con un **score de relevancia (0-100)** basado en:
   - 📅 Recencia (publicado hoy/ayer)
   - 🤗 Destacado por la comunidad HuggingFace
   - 💻 Código público disponible
   - 📈 Velocidad de citación (impresionante para un paper nuevo)
   - 🔬 Señales de novedad en el abstract
   - 🎯 Match con temas de interés personal (reporte filtrado)
4. Se generan **dos reportes en Markdown**:
   - `YYYY-MM-DD_general.md` — todos los papers con score ≥ 30
   - `YYYY-MM-DD_filtrado.md` — papers en tus temas con score ≥ 45

## Leer los reportes

➡️ **[Ver índice de reportes](reports/README.md)**

O directamente en `reports/` ordenados por fecha.

## Configuración

Edita `scripts/fetch_papers.py` para personalizar:

```python
# Tus temas de interés (para el reporte filtrado)
PERSONAL_TOPICS = [
    "cybersecurity", "information security",
    "large language models", "LLM",
    # ... agrega los tuyos
]

# Categorías de arXiv a monitorear
ARXIV_CATEGORIES = [
    "cs.CR",  # Cryptography and Security
    "cs.AI",  # Artificial Intelligence
    # ... ver lista completa en arxiv.org
]

# Umbrales de score
MIN_SCORE_GENERAL  = 30   # mínimo para reporte general
MIN_SCORE_FILTERED = 45   # mínimo para reporte filtrado
```

## Ejecutar manualmente

```bash
python scripts/fetch_papers.py
```

Los reportes se guardan en `reports/`.

También puedes **triggear manualmente** desde GitHub:  
`Actions` → `Paper Radar — Daily Report` → `Run workflow`

---

*Paper Radar — construido con Python puro, sin dependencias externas.*

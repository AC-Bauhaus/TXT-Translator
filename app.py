
import json
import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import io
import re
import sys
import time
import uuid
import threading

from functools import lru_cache
from pathlib import Path

import argostranslate.settings as argos_settings

from flask import Flask, jsonify, render_template, request, send_file


def resource_path(relative):
    """Resolve recursos tanto no projeto quanto em um executável empacotado."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / relative)


def settings_path():
    """Armazena as preferências fora da pasta do aplicativo."""
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "TXTTradutor" / "settings.json"

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "TXTTradutor"
            / "settings.json"
        )

    base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "txt-tradutor" / "settings.json"


def load_settings():
    path = settings_path()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid settings")
    except (OSError, ValueError, json.JSONDecodeError):
        data = {}

    data.setdefault("protected", "")
    data.setdefault("glossary", [])

    if not isinstance(data["glossary"], list):
        data["glossary"] = []

    return data


def save_settings(data):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


app = Flask(__name__, template_folder=resource_path("templates"))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

TRANSLATION_MODES = {
    "fast": {
        "name": "Rápido",
        "chunk_size": 8000,
        "description": "Prioriza a velocidade de processamento.",
    },
    "balanced": {
        "name": "Equilibrado",
        "chunk_size": 4000,
        "description": "Equilibra velocidade e segmentação do texto.",
    },
    "quality": {
        "name": "Melhor qualidade",
        "chunk_size": 1800,
        "description": (
            "Processa trechos menores para preservar melhor o contexto local."
        ),
    },
}

# As tarefas são compartilhadas entre as rotas HTTP e as threads de tradução.
translation_jobs = {}
translation_jobs_lock = threading.Lock()


LANGUAGES = {
    "en": "Inglês",
    "pt": "Português",
    "pb": "Português (Brasil)",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
    "ja": "Japonês",
    "ko": "Coreano",
    "zh": "Chinês",
    "ru": "Russo",
    "nl": "Holandês",
    "pl": "Polonês",
    "tr": "Turco",
    "uk": "Ucraniano",
    "ar": "Árabe",
    "az": "Azerbaijano",
    "eu": "Basco",
    "ca": "Catalão",
    "cs": "Tcheco",
    "da": "Dinamarquês",
    "eo": "Esperanto",
    "fa": "Persa",
    "fi": "Finlandês",
    "gl": "Galego",
    "ga": "Irlandês",
    "el": "Grego",
    "he": "Hebraico",
    "hi": "Hindi",
    "hu": "Húngaro",
    "id": "Indonésio",
    "ky": "Quirguiz",
    "ms": "Malaio",
    "sv": "Sueco",
    "sw": "Suaíli",
    "ur": "Urdu",
    "auto": "Detectar idioma",
}


# Prioriza velocidade de geração no Argos Translate.
argos_settings.beam_size = 1


@lru_cache(maxsize=32)
def get_translation_model(source, target):
    import argostranslate.translate

    translation = argostranslate.translate.get_translation_from_codes(
        source,
        target,
    )

    if translation is None:
        raise RuntimeError(
            f"Não existe modelo instalado para {source} → {target}."
        )

    return translation


def translate_chunk(text, source, target):
    try:
        translation = get_translation_model(source, target)
        result = translation.translate(text)

    except ImportError as exc:
        raise RuntimeError(
            "O mecanismo de tradução offline não está instalado. "
            "Consulte o README para instalar as dependências."
        ) from exc

    except Exception as exc:
        raise RuntimeError(f"Falha no mecanismo local: {exc}") from exc

    return text if result is None else result


def placeholder_token(index):
    return f"ZXQKEEP{uuid.uuid4().hex.upper()}N{index:04d}QXZ"


def compile_term_pattern(term):
    """Localiza palavras/expressões inteiras, sem substituir partes de palavras."""
    return re.compile(
        r"(?<!\w)" + re.escape(term) + r"(?!\w)",
        re.IGNORECASE | re.UNICODE,
    )


def protect_and_apply_glossary(text, terms, glossary, source, target):
    replacements = {}
    index = 0
    applicable = []

    for entry in glossary:
        if not isinstance(entry, dict):
            continue

        original = str(entry.get("source", "")).strip()
        translated = str(entry.get("translation", "")).strip()
        src_lang = entry.get("source_lang", "*")
        dst_lang = entry.get("target_lang", "*")

        if (
            original
            and translated
            and src_lang in ("*", source)
            and dst_lang in ("*", target)
        ):
            applicable.append(
                (
                    original,
                    translated,
                    int(src_lang == source) + int(dst_lang == target),
                )
            )

    # Regras mais longas e específicas têm prioridade.
    for original, translated, _specificity in sorted(
        applicable,
        key=lambda pair: (len(pair[0]), pair[2]),
        reverse=True,
    ):
        token = placeholder_token(index)
        index += 1

        text, count = compile_term_pattern(original).subn(
            lambda _match: token,
            text,
        )

        if count:
            replacements[token] = translated

    # Termos protegidos mantêm a grafia original. O glossário é aplicado primeiro.
    for term in sorted(set(terms), key=len, reverse=True):
        term = term.strip()

        if not term:
            continue

        token = placeholder_token(index)
        index += 1

        text, count = compile_term_pattern(term).subn(
            lambda _match: token,
            text,
        )

        if count:
            replacements[token] = term

    return text, replacements


def detect_language(text):
    try:
        from langdetect import detect, LangDetectException

        try:
            return detect(text[:10000])

        except LangDetectException as exc:
            raise ValueError(
                "Não foi possível detectar o idioma. "
                "Selecione o idioma de origem manualmente."
            ) from exc

    except ImportError as exc:
        raise RuntimeError(
            "O detector local de idioma não está instalado. "
            "Reinstale as dependências do aplicativo."
        ) from exc


def infer_portuguese_gender(word):
    """Heurística simples para inferir gênero de palavras em português."""
    parts = word.strip().split()

    if not parts:
        return None

    word = parts[-1].lower().strip(".,;:!?")

    feminine_exceptions = {
        "palavra", "mão", "flor", "cor", "dor", "noite",
        "ponte", "fonte", "imagem", "viagem", "linguagem",
    }

    masculine_exceptions = {
        "dia", "mapa", "problema", "sistema", "programa",
        "planeta", "poema", "clima",
    }

    if word in feminine_exceptions:
        return "f"

    if word in masculine_exceptions:
        return "m"

    if word.endswith(("ção", "são", "dade", "gem", "ice")):
        return "f"

    if word.endswith(("o", "or")):
        return "m"

    if word.endswith("a"):
        return "f"

    return None


def correct_portuguese_article(text, token, translation):
    """Corrige artigos imediatamente anteriores a um termo do glossário."""
    gender = infer_portuguese_gender(translation)

    if gender is None:
        return text

    replacements = (
        {"o": "a", "os": "as", "um": "uma", "uns": "umas"}
        if gender == "f"
        else {"a": "o", "as": "os", "uma": "um", "umas": "uns"}
    )

    pattern = re.compile(
        r"\b(o|a|os|as|um|uma|uns|umas)(\s+)"
        + re.escape(token)
        + r"\b",
        re.IGNORECASE,
    )

    def fix(match):
        article = match.group(1)
        new_article = replacements.get(article.lower(), article)

        if article.isupper():
            new_article = new_article.upper()
        elif article.istitle():
            new_article = new_article.capitalize()

        return new_article + match.group(2) + token

    return pattern.sub(fix, text)


def translate_text(
    text,
    source,
    target,
    terms,
    glossary,
    mode="balanced",
    progress_callback=None,
):
    """Traduz texto e informa o avanço após concluir cada trecho."""
    if not text.strip():
        if progress_callback:
            progress_callback(1.0)

        return text

    if source == "auto":
        source = detect_language(text)

    protected, replacements = protect_and_apply_glossary(
        text,
        terms,
        glossary,
        source,
        target,
    )

    if source == target:
        result = protected

        if progress_callback:
            progress_callback(1.0)

    else:
        mode_settings = TRANSLATION_MODES.get(
            mode,
            TRANSLATION_MODES["balanced"],
        )

        chunk_size = mode_settings["chunk_size"]
        split_size = max(500, int(chunk_size * 0.875))

        translation_units = []
        chunks = re.split(r"(\n)", protected)

        for chunk in chunks:
            if chunk == "\n" or chunk == "":
                translation_units.append((False, chunk))
                continue

            if len(chunk) <= chunk_size:
                translation_units.append((True, chunk))

            else:
                pieces = re.split(r"(?<=[.!?。！？])\s+", chunk)
                buffer = ""

                for piece in pieces:
                    if (
                        buffer
                        and len(buffer) + len(piece) + 1 > split_size
                    ):
                        translation_units.append((True, buffer))
                        buffer = ""

                    buffer += (" " if buffer else "") + piece

                if buffer:
                    translation_units.append((True, buffer))

        total_weight = sum(
            max(1, len(unit))
            for should_translate, unit in translation_units
            if should_translate
        )

        completed_weight = 0
        translated = []

        for should_translate, unit in translation_units:
            if not should_translate:
                translated.append(unit)
                continue

            translated.append(
                translate_chunk(unit, source, target)
            )

            completed_weight += max(1, len(unit))

            if progress_callback and total_weight:
                progress_callback(
                    min(1.0, completed_weight / total_weight)
                )

        if progress_callback and not total_weight:
            progress_callback(1.0)

        result = "".join(translated)

    # Restaura termos protegidos e entradas do glossário.
    for token, replacement in replacements.items():
        if target in ("pt", "pb"):
            result = correct_portuguese_article(
                result,
                token,
                replacement,
            )

        result = result.replace(token, replacement)

    return result


@app.get("/")
def index():
    """Página principal do aplicativo."""
    return render_template(
        "index.html",
        languages={
            key: value
            for key, value in LANGUAGES.items()
            if key != "auto"
        },
        source_languages=LANGUAGES,
    )


@app.get("/settings")
def get_settings():
    return jsonify(load_settings())


@app.post("/settings")
def update_settings():
    incoming = request.get_json(silent=True) or {}
    current = load_settings()

    if "protected" in incoming:
        current["protected"] = str(incoming.get("protected", ""))

    if "glossary" in incoming and isinstance(incoming["glossary"], list):
        cleaned = []

        for entry in incoming["glossary"]:
            if not isinstance(entry, dict):
                continue

            original = str(entry.get("source", "")).strip()
            translated = str(entry.get("translation", "")).strip()

            if not original or not translated:
                continue

            src = str(entry.get("source_lang", "*"))
            dst = str(entry.get("target_lang", "*"))

            if src not in LANGUAGES and src != "*":
                src = "*"

            if dst not in LANGUAGES and dst != "*":
                dst = "*"

            cleaned.append(
                {
                    "source": original,
                    "translation": translated,
                    "source_lang": src,
                    "target_lang": dst,
                }
            )

        current["glossary"] = cleaned

    save_settings(current)

    return jsonify(ok=True, settings=current)


@app.get("/status")
def status():
    try:
        import argostranslate.translate

        installed = [
            {
                "code": language.code,
                "name": LANGUAGES.get(language.code, language.name),
            }
            for language in argostranslate.translate.get_installed_languages()
        ]

    except Exception:
        installed = []

    return jsonify(
        offline=True,
        installed_languages=installed,
        available_languages=[
            {"code": key, "name": value}
            for key, value in LANGUAGES.items()
            if key != "auto"
        ],
    )


@app.post("/models/download")
def download_model():
    payload = request.get_json(silent=True) or {}

    source = str(payload.get("source", ""))
    target = str(payload.get("target", ""))

    if (
        source not in LANGUAGES
        or target not in LANGUAGES
        or source in ("auto", target)
    ):
        return jsonify(
            error=(
                "Escolha dois idiomas diferentes e uma origem específica "
                "(não use Detectar idioma)."
            )
        ), 400

    try:
        import argostranslate.package as package

        package.update_package_index()

        candidates = [
            package_item
            for package_item in package.get_available_packages()
            if package_item.from_code == source
            and package_item.to_code == target
        ]

        if not candidates:
            return jsonify(
                error=(
                    f"O catálogo não oferece um modelo direto para "
                    f"{source} → {target}. Tente instalar modelos via "
                    "um idioma intermediário, como inglês."
                )
            ), 404

        chosen = candidates[0]
        downloaded_path = chosen.download()

        package.install_from_path(downloaded_path)

        return jsonify(
            ok=True,
            message=(
                f"Modelo {LANGUAGES[source]} → {LANGUAGES[target]} "
                "instalado. A tradução desse par poderá ser feita offline."
            ),
        )

    except Exception as exc:
        app.logger.exception("Erro ao baixar/instalar modelo")

        return jsonify(
            error=f"Não foi possível baixar/instalar o modelo: {exc}"
        ), 500


def translate_pdf(
    data,
    source,
    target,
    terms,
    glossary,
    mode="balanced",
    progress_callback=None,
):
    """Traduz blocos de texto de um PDF e informa o progresso real."""
    try:
        import fitz

    except ImportError as exc:
        raise RuntimeError(
            "A biblioteca PyMuPDF não está instalada."
        ) from exc

    document = fitz.open(stream=data, filetype="pdf")

    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    font_path = next(
        (
            candidate
            for candidate in font_candidates
            if os.path.isfile(candidate)
        ),
        None,
    )

    try:
        # Reúne os blocos válidos para calcular o peso de cada parte do PDF.
        pages_with_blocks = []
        total_weight = 0

        for page in document:
            valid_blocks = []

            for block in page.get_text("blocks"):
                if len(block) < 5 or not isinstance(block[4], str):
                    continue

                original = block[4].strip()

                if not original:
                    continue

                rect = fitz.Rect(block[:4])

                if rect.is_empty or rect.is_infinite:
                    continue

                weight = max(1, len(original))

                valid_blocks.append((rect, block[4], weight))
                total_weight += weight

            pages_with_blocks.append((page, valid_blocks))

        completed_weight = 0
        translated_pages = []

        if progress_callback:
            progress_callback(0.0)

        # Traduz cada bloco e acompanha também os trechos internos dele.
        for page, original_blocks in pages_with_blocks:
            text_blocks = []

            for rect, original_text, block_weight in original_blocks:
                block_base = completed_weight

                def report_block_progress(
                    fraction,
                    base=block_base,
                    weight=block_weight,
                ):
                    if progress_callback and total_weight:
                        overall = (
                            base + weight * fraction
                        ) / total_weight

                        progress_callback(min(1.0, overall))

                translated = translate_text(
                    original_text,
                    source,
                    target,
                    terms,
                    glossary,
                    mode=mode,
                    progress_callback=report_block_progress,
                )

                text_blocks.append((rect, translated))
                completed_weight += block_weight

                if progress_callback and total_weight:
                    progress_callback(
                        min(1.0, completed_weight / total_weight)
                    )

            translated_pages.append((page, text_blocks))

        # Depois de traduzir os textos, aplica as alterações visuais no PDF.
        for page, text_blocks in translated_pages:
            for rect, _translated in text_blocks:
                page.add_redact_annot(rect, fill=(1, 1, 1))

            if text_blocks:
                page.apply_redactions(images=0, graphics=0)

            for rect, translated in text_blocks:
                rect = rect + (1, 1, -1, -1)
                fontsize = 10
                inserted = False

                while fontsize >= 5:
                    kwargs = {
                        "rect": rect,
                        "buffer": translated,
                        "fontsize": fontsize,
                        "fontname": "helv",
                        "align": 0,
                    }

                    if font_path:
                        kwargs["fontfile"] = font_path
                        kwargs["fontname"] = "DejaVuSans"

                    result = page.insert_textbox(**kwargs)

                    if result >= 0:
                        inserted = True
                        break

                    # Remove a tentativa anterior antes de reduzir a fonte.
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page.apply_redactions(images=0, graphics=0)

                    fontsize -= 1

                if not inserted:
                    fallback_kwargs = {
                        "rect": rect,
                        "buffer": translated[:2000],
                        "fontsize": 5,
                        "fontname": (
                            "DejaVuSans" if font_path else "helv"
                        ),
                    }

                    if font_path:
                        fallback_kwargs["fontfile"] = font_path

                    page.insert_textbox(**fallback_kwargs)

        output = io.BytesIO(document.tobytes())
        output.seek(0)

        if progress_callback:
            progress_callback(1.0)

        return output

    finally:
        document.close()


def update_translation_job(job_id, progress):
    """Atualiza o progresso compartilhado com a interface."""
    with translation_jobs_lock:
        job = translation_jobs.get(job_id)

        if job is None:
            return

        new_progress = min(99.0, max(0.0, float(progress)))

        job["progress"] = max(
            job.get("progress", 0.0),
            new_progress,
        )


def run_translation_job(
    job_id,
    data,
    filename,
    extension,
    source,
    target,
    terms,
    glossary,
    mode,
):
    """Executa a tradução em segundo plano e armazena o resultado."""
    try:
        update_translation_job(job_id, 3)

        if extension == ".txt":
            try:
                original = data.decode("utf-8-sig")

            except UnicodeDecodeError as exc:
                raise ValueError(
                    "Não foi possível ler o TXT como UTF-8. "
                    "Salve-o em UTF-8 e tente novamente."
                ) from exc

            output = translate_text(
                original,
                source,
                target,
                terms,
                glossary,
                mode=mode,
                progress_callback=lambda fraction: update_translation_job(
                    job_id,
                    5 + fraction * 85,
                ),
            )

            result = {
                "kind": "txt",
                "payload": {
                    "filename": f"{Path(filename).stem}_{target}.txt",
                    "translated": output,
                    "original_chars": len(original),
                    "translated_chars": len(output),
                },
            }

        else:
            output = translate_pdf(
                data,
                source,
                target,
                terms,
                glossary,
                mode=mode,
                progress_callback=lambda fraction: update_translation_job(
                    job_id,
                    5 + fraction * 80,
                ),
            )

            result = {
                "kind": "pdf",
                "filename": f"{Path(filename).stem}_{target}.pdf",
                "data": output.getvalue(),
            }

        # Reserva o final da barra para a preparação do resultado.
        update_translation_job(job_id, 96)

        with translation_jobs_lock:
            job = translation_jobs.get(job_id)

            if job is not None:
                job["result"] = result
                job["progress"] = 100.0
                job["status"] = "completed"
                job["updated_at"] = time.time()

    except Exception as exc:
        app.logger.exception("Erro na tarefa de tradução")

        message = str(exc)

        if (
            "not installed" in message.lower()
            or "no translation" in message.lower()
            or "translation" in message.lower()
        ):
            message += (
                "\n\nVerifique se o modelo offline para esse par de "
                "idiomas foi instalado."
            )

        with translation_jobs_lock:
            job = translation_jobs.get(job_id)

            if job is not None:
                job["error"] = message
                job["status"] = "error"
                job["updated_at"] = time.time()


@app.post("/translate")
def translate():
    """Valida o arquivo, cria uma tarefa e retorna seu identificador."""
    if "file" not in request.files:
        return jsonify(
            error="Selecione um arquivo .TXT ou .PDF."
        ), 400

    file = request.files["file"]
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in (".txt", ".pdf"):
        return jsonify(
            error="Formato não suportado. Use .TXT ou .PDF."
        ), 400

    data = file.read()

    if not data:
        return jsonify(error="O arquivo está vazio."), 400

    source = request.form.get("source", "auto")
    target = request.form.get("target", "pb")
    mode = request.form.get("mode", "balanced")

    if mode not in TRANSLATION_MODES:
        mode = "balanced"

    if target == "auto" or target not in LANGUAGES:
        return jsonify(
            error="Selecione um idioma de destino válido."
        ), 400

    if source not in LANGUAGES:
        source = "auto"

    settings = load_settings()

    protected_text = request.form.get(
        "protected",
        settings.get("protected", ""),
    )

    terms = [
        line.strip()
        for line in protected_text.splitlines()
        if line.strip()
    ]

    glossary = settings.get("glossary", [])

    job_id = uuid.uuid4().hex
    now = time.time()

    with translation_jobs_lock:
        # Limpa apenas tarefas concluídas/erro antigas.
        # Não remove uma tradução que ainda esteja rodando.
        for old_id, old_job in list(translation_jobs.items()):
            updated_at = old_job.get(
                "updated_at",
                old_job.get("created_at", now),
            )

            if (
                old_job.get("status") != "running"
                and now - updated_at > 3600
            ):
                translation_jobs.pop(old_id, None)

        translation_jobs[job_id] = {
            "status": "running",
            "progress": 1.0,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

    worker = threading.Thread(
        target=run_translation_job,
        args=(
            job_id,
            data,
            filename,
            extension,
            source,
            target,
            terms,
            glossary,
            mode,
        ),
        daemon=True,
    )

    worker.start()

    return jsonify(job_id=job_id), 202


@app.get("/translate/progress/<job_id>")
def translation_progress(job_id):
    """Retorna o estado e a porcentagem atual da tarefa."""
    with translation_jobs_lock:
        job = translation_jobs.get(job_id)

        if job is None:
            return jsonify(
                error="Tarefa de tradução não encontrada ou expirada."
            ), 404

        response = {
            "status": job["status"],
            "progress": job["progress"],
        }

        if job["status"] == "error":
            response["error"] = job["error"]
            translation_jobs.pop(job_id, None)

    return jsonify(response)


@app.get("/translate/result/<job_id>")
def translation_result(job_id):
    """Entrega o resultado quando a tarefa termina."""
    with translation_jobs_lock:
        job = translation_jobs.get(job_id)

        if job is None:
            return jsonify(
                error="Resultado não encontrado ou expirado."
            ), 404

        if job["status"] == "error":
            message = job["error"]
            translation_jobs.pop(job_id, None)

            return jsonify(error=message), 500

        if job["status"] != "completed":
            return jsonify(
                error="A tradução ainda não foi concluída."
            ), 409

        result = job["result"]
        translation_jobs.pop(job_id, None)

    if result["kind"] == "txt":
        return jsonify(result["payload"])

    return send_file(
        io.BytesIO(result["data"]),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=result["filename"],
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
import json
import os
import re
import sys
import uuid
import io
import tempfile
import argostranslate.settings as argos_settings
import zipfile
import xml.etree.ElementTree as ET
from lxml import etree
from functools import lru_cache
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file


def resource_path(relative):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / relative)


def settings_path():
    """Store preferences outside the app folder so they survive upgrades."""
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "TXTTradutor" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TXTTradutor" / "settings.json"
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
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


app = Flask(__name__, template_folder=resource_path("templates"))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# Languages offered by the Argos Translate model catalog. A language appearing here
# does not mean a model is already installed: the requested pair must be installed.
LANGUAGES = {
    "en": "Inglês", "pt": "Português", "pb": "Português (Brasil)",
    "es": "Espanhol", "fr": "Francês", "de": "Alemão", "it": "Italiano",
    "ja": "Japonês", "ko": "Coreano", "zh": "Chinês", "ru": "Russo",
    "nl": "Holandês", "pl": "Polonês", "tr": "Turco", "uk": "Ucraniano",
    "ar": "Árabe", "az": "Azerbaijano", "eu": "Basco", "ca": "Catalão",
    "cs": "Tcheco", "da": "Dinamarquês", "eo": "Esperanto", "fa": "Persa",
    "fi": "Finlandês", "gl": "Galego", "ga": "Irlandês", "el": "Grego",
    "he": "Hebraico", "hi": "Hindi", "hu": "Húngaro", "id": "Indonésio",
    "ky": "Quirguiz", "ms": "Malaio", "sv": "Sueco", "sw": "Suaíli",
    "ur": "Urdu", "auto": "Detectar idioma"
}


def placeholder_token(index):
    return f"ZXQKEEP{uuid.uuid4().hex.upper()}N{index:04d}QXZ"


def compile_term_pattern(term):
    # Match whole words/phrases, case-insensitively, without replacing a term inside
    # a larger word (e.g. 'word' should not replace 'sword').
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE | re.UNICODE)


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
        if original and translated and src_lang in ("*", source) and dst_lang in ("*", target):
            applicable.append((original, translated, int(src_lang == source) + int(dst_lang == target)))

    # Longest and most specific rules win over shorter or wildcard rules.
    for original, translated, _specificity in sorted(applicable, key=lambda pair: (len(pair[0]), pair[2]), reverse=True):
        token = placeholder_token(index)
        index += 1
        pattern = compile_term_pattern(original)
        text, count = pattern.subn(lambda _match: token, text)
        if count:
            replacements[token] = translated

    # Protected terms preserve their original spelling. Glossary rules are applied
    # first, so a deliberate glossary translation wins if the same term is listed twice.
    for term in sorted(set(terms), key=len, reverse=True):
        term = term.strip()
        if not term:
            continue
        token = placeholder_token(index)
        index += 1
        text, count = compile_term_pattern(term).subn(lambda _match: token, text)
        if count:
            replacements[token] = term
    return text, replacements


def detect_language(text):
    try:
        from langdetect import detect, LangDetectException
        try:
            return detect(text[:10000])
        except LangDetectException:
            raise ValueError("Não foi possível detectar o idioma. Selecione o idioma de origem manualmente.")
    except ImportError:
        raise RuntimeError("O detector local de idioma não está instalado. Reinstale as dependências do aplicativo.")

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
        raise RuntimeError(
            f"Falha no mecanismo local: {exc}"
        ) from exc

    return text if result is None else result

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

def translate_text(text, source, target, terms, glossary):
    if not text.strip():
        return text
    if source == "auto":
        source = detect_language(text)
    protected, replacements = protect_and_apply_glossary(text, terms, glossary, source, target)
    if source == target:
        result = protected
    else:
        chunks = re.split(r"(\n)", protected)
        translated = []
        for chunk in chunks:
            if chunk == "\n" or chunk == "":
                translated.append(chunk)
                continue
            if len(chunk) <= 8000:
                translated.append(translate_chunk(chunk, source, target))
            else:
                pieces = re.split(r"(?<=[.!?。！？])\s+", chunk)
                buffer = ""
                for piece in pieces:
                    if buffer and len(buffer) + len(piece) + 1 > 7000:
                        translated.append(translate_chunk(buffer, source, target))
                        buffer = ""
                    buffer += (" " if buffer else "") + piece
                if buffer:
                    translated.append(translate_chunk(buffer, source, target))
        result = "".join(translated)
    # Exact placeholder restoration also protects glossary terms from model changes.
    for token, replacement in replacements.items():
        if target in ("pt", "pb"):
            result = correct_portuguese_article(
                result, token, replacement
            )
        result = result.replace(token, replacement)

    return result


@app.get("/")
def index():
    return render_template("index.html", languages={k: v for k, v in LANGUAGES.items() if k != "auto"}, source_languages=LANGUAGES)


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
            cleaned.append({"source": original, "translation": translated, "source_lang": src, "target_lang": dst})
        current["glossary"] = cleaned
    save_settings(current)
    return jsonify(ok=True, settings=current)


@app.get("/status")
def status():
    try:
        import argostranslate.translate
        installed = [{"code": lang.code, "name": LANGUAGES.get(lang.code, lang.name)} for lang in argostranslate.translate.get_installed_languages()]
    except Exception:
        installed = []
    return jsonify(offline=True, installed_languages=installed, available_languages=[{"code": k, "name": v} for k, v in LANGUAGES.items() if k != "auto"])


@app.post("/models/download")
def download_model():
    payload = request.get_json(silent=True) or {}
    source = str(payload.get("source", ""))
    target = str(payload.get("target", ""))
    if source not in LANGUAGES or target not in LANGUAGES or source in ("auto", target):
        return jsonify(error="Escolha dois idiomas diferentes e uma origem específica (não use Detectar idioma)."), 400
    try:
        import argostranslate.package as package
        package.update_package_index()
        candidates = [p for p in package.get_available_packages() if p.from_code == source and p.to_code == target]
        if not candidates:
            return jsonify(error=f"O catálogo não oferece um modelo direto para {source} → {target}. Tente instalar modelos via um idioma intermediário, como inglês."), 404
        chosen = candidates[0]
        downloaded_path = chosen.download()
        package.install_from_path(downloaded_path)
        return jsonify(ok=True, message=f"Modelo {LANGUAGES[source]} → {LANGUAGES[target]} instalado. A tradução desse par poderá ser feita offline.")
    except Exception as exc:
        return jsonify(error=f"Não foi possível baixar/instalar o modelo: {exc}"), 500

def replace_paragraph_text(paragraph, new_text):
    """Substitui o texto sem remover o estilo geral do parágrafo."""
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(new_text)



def translate_docx(data, source, target, terms, glossary):
    """
    Traduz textos de DOCX editando os XMLs do pacote original.
    Preserva imagens, relacionamentos, estilos e estrutura do documento.
    """
    W_NS = (
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    )
    XML_NS = "http://www.w3.org/XML/1998/namespace"

    ns = {"w": W_NS}

    def wtag(name):
        return f"{{{W_NS}}}{name}"

    output = io.BytesIO()

    with zipfile.ZipFile(io.BytesIO(data), "r") as source_zip:
        with zipfile.ZipFile(
            output, "w", zipfile.ZIP_DEFLATED
        ) as output_zip:

            for item in source_zip.infolist():
                content = source_zip.read(item.filename)
                filename = item.filename

                # Processa XMLs do Word, incluindo notas de rodapé,
                # notas de fim, cabeçalhos e rodapés.
                is_word_xml = (
                    filename.startswith("word/")
                    and filename.endswith(".xml")
                    and not filename.endswith(".rels")
                )

                if not is_word_xml:
                    output_zip.writestr(item, content)
                    continue

                try:
                    root = etree.fromstring(content)
                except etree.XMLSyntaxError:
                    output_zip.writestr(item, content)
                    continue

                # Formatações que fazem o trecho permanecer no original.
                special_formatting = {
                    "rStyle", "b", "bCs", "i", "iCs",
                    "u", "strike", "dstrike", "color", "highlight",
                    "shd", "caps", "smallCaps", "outline", "shadow",
                    "emboss", "imprint", "vanish", "webHidden",
                    "vertAlign", "bdr", "spacing", "position",
                    "sz", "szCs", "rFonts",
                }

                def is_styled_run(run):
                    properties = run.xpath("./w:rPr/*", namespaces=ns)

                    for prop in properties:
                        name = etree.QName(prop).localname

                        if name not in special_formatting:
                            continue

                        value = prop.get(wtag("val"), "").lower()

                        if value in ("0", "false", "off", "none"):
                            continue

                        return True

                    return False
                
                paragraphs = root.xpath(".//w:p", namespaces=ns)

                for paragraph in paragraphs:
                    if paragraph.xpath(
                        ".//w:fldChar | .//w:instrText",
                        namespaces=ns,
                    ):
                        continue

                    # Reúne nós de texto e identifica o estilo de cada um.
                    text_nodes = paragraph.xpath(
                        ".//w:t",
                        namespaces=ns,
                    )

                    if not text_nodes:
                        continue

                    original_parts = [
                        node.text or "" for node in text_nodes
                    ]
                    original = "".join(original_parts)

                    if not original.strip():
                        continue

                    leading = original[:len(original) - len(original.lstrip())]
                    trailing = original[len(original.rstrip()):]
                    core = original.strip()

                    translated = translate_text(
                        core, source, target, terms, glossary
                    ).strip()

                    if not translated:
                        continue

                    # Mapeia os limites dos nós originais na frase completa.
                    import difflib

                    token_pattern = re.compile(r"\s+|[^\W\s]+|[^\w\s]", re.UNICODE)

                    original_tokens = []
                    token_nodes = []
                    offset = 0

                    for index, part in enumerate(original_parts):
                        for match in token_pattern.finditer(part):
                            original_tokens.append(match.group())
                            token_nodes.append(index)
                        offset += len(part)

                    translated_tokens = token_pattern.findall(translated)

                    if not original_tokens or not translated_tokens:
                        text_nodes[0].text = leading + translated + trailing
                        for node in text_nodes[1:]:
                            node.text = ""
                        continue

                    # Alinha tokens iguais entre original e tradução.
                    # Os tokens não alinhados são distribuídos entre os
                    # limites dos tokens correspondentes mais próximos.
                    matcher = difflib.SequenceMatcher(
                        None,
                        [
                            token.casefold()
                            for token in original_tokens
                        ],
                        [
                            token.casefold()
                            for token in translated_tokens
                        ],
                        autojunk=False,
                    )

                    original_boundaries = [0] * (
                        len(original_tokens) + 1
                    )

                    for i, node_index in enumerate(token_nodes):
                        original_boundaries[i] = node_index

                    original_boundaries[len(original_tokens)] = (
                        len(text_nodes) - 1
                    )

                    assignments = [[] for _ in text_nodes]

                    # Constrói posições de corte usando os nós de origem.
                    cuts = [0] * (len(text_nodes) + 1)
                    for i, node_index in enumerate(token_nodes):
                        cuts[node_index + 1] = i + 1

                    for i in range(1, len(cuts)):
                        if cuts[i] == 0:
                            cuts[i] = cuts[i - 1]

                    cuts[-1] = len(original_tokens)

                    token_to_node = {}
                    for node_index in range(len(text_nodes)):
                        for token_index in range(
                            cuts[node_index], cuts[node_index + 1]
                        ):
                            token_to_node[token_index] = node_index

                    # Usa correspondências exatas como âncoras.
                    anchors = []
                    for block in matcher.get_matching_blocks():
                        for delta in range(block.size):
                            oi = block.a + delta
                            ti = block.b + delta
                            anchors.append((ti, token_to_node.get(oi, 0)))

                    anchors.sort()

                    # Distribui sequências traduzidas entre as âncoras.
                    for ti, token in enumerate(translated_tokens):
                        previous = [
                            node_index
                            for anchor_t, node_index in anchors
                            if anchor_t <= ti
                        ]
                        following = [
                            node_index
                            for anchor_t, node_index in anchors
                            if anchor_t >= ti
                        ]

                        if previous:
                            node_index = previous[-1]
                        elif following:
                            node_index = following[0]
                        else:
                            node_index = 0

                        assignments[node_index].append(token)

                    # Recompõe os nós existentes sem remover suas tags.
                    for index, node in enumerate(text_nodes):
                        piece = "".join(assignments[index])

                        if index == 0:
                            piece = leading + piece

                        if index == len(text_nodes) - 1:
                            piece += trailing

                        node.text = piece

                        if piece.startswith(" ") or piece.endswith(" "):
                            node.set(
                                f"{{{XML_NS}}}space", "preserve"
                            )
                        else:
                            node.attrib.pop(
                                f"{{{XML_NS}}}space", None
                            )

                content = etree.tostring(
                    root,
                    encoding="UTF-8",
                    xml_declaration=True,
                    standalone=True,
                )

                output_zip.writestr(item, content)

    output.seek(0)
    return output


def translate_pdf(data, source, target, terms, glossary):
    """
    Traduz blocos de texto dentro das páginas do PDF.
    A posição é preservada aproximadamente; o layout pode variar.
    """
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("A biblioteca PyMuPDF não está instalada.") from exc

    document = fitz.open(stream=data, filetype="pdf")

    # Fontes Unicode comuns no Linux e no Windows.
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    font_path = next(
        (path for path in font_candidates if os.path.isfile(path)),
        None,
    )

    try:
        for page in document:
            blocks = page.get_text("blocks")
            text_blocks = []

            for block in blocks:
                if len(block) < 5 or not isinstance(block[4], str):
                    continue

                original = block[4].strip()
                if not original:
                    continue

                rect = fitz.Rect(block[:4])
                if rect.is_empty or rect.is_infinite:
                    continue

                translated = translate_text(
                    block[4], source, target, terms, glossary
                )
                text_blocks.append((rect, translated))

            # Oculta o texto antigo antes de inserir as traduções.
            for rect, _ in text_blocks:
                page.add_redact_annot(rect, fill=(1, 1, 1))

            if text_blocks:
                page.apply_redactions(images=0, graphics=0)

            for rect, translated in text_blocks:
                # Pequena margem para não encostar o texto nas bordas.
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

                    # Remove qualquer tentativa anterior antes de tentar
                    # novamente com fonte menor.
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page.apply_redactions(images=0, graphics=0)
                    fontsize -= 1

                if not inserted:
                    # Não interrompe a tradução inteira por um bloco longo.
                    page.insert_textbox(
                        rect,
                        translated[:2000],
                        fontsize=5,
                        fontfile=font_path if font_path else None,
                        fontname="DejaVuSans" if font_path else "helv",
                    )

        output = io.BytesIO(document.tobytes())
        output.seek(0)
        return output
    finally:
        document.close()

@app.post("/translate")
def translate():
    if "file" not in request.files:
        return jsonify(error="Selecione um arquivo .TXT, .PDF ou .DOCX."), 400

    file = request.files["file"]
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()

    if extension not in (".txt", ".pdf", ".docx"):
        return jsonify(error="Formato não suportado. Use .TXT, .PDF ou .DOCX."), 400

    try:
        data = file.read()

        if not data:
            return jsonify(error="O arquivo está vazio."), 400

        source = request.form.get("source", "auto")
        target = request.form.get("target", "pt")

        if target == "auto" or target not in LANGUAGES:
            return jsonify(error="Selecione um idioma de destino válido."), 400

        if source not in LANGUAGES:
            source = "auto"

        settings = load_settings()
        protected_text = request.form.get(
            "protected", settings.get("protected", "")
        )
        terms = [
            line.strip()
            for line in protected_text.splitlines()
            if line.strip()
        ]
        glossary = settings.get("glossary", [])

        if extension == ".txt":
            try:
                original = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                return jsonify(
                    error="Não foi possível ler o TXT como UTF-8. "
                          "Salve-o em UTF-8 e tente novamente."
                ), 400

            output = translate_text(
                original, source, target, terms, glossary
            )
            translated_filename = f"{Path(filename).stem}_{target}.txt"

            return jsonify(
                filename=translated_filename,
                translated=output,
                original_chars=len(original),
                translated_chars=len(output),
            )

        if extension == ".docx":
            output = translate_docx(
                data, source, target, terms, glossary
            )
            mime_type = (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            )
        else:
            output = translate_pdf(
                data, source, target, terms, glossary
            )
            mime_type = "application/pdf"

        translated_filename = f"{Path(filename).stem}_{target}{extension}"

        return send_file(
            output,
            mimetype=mime_type,
            as_attachment=True,
            download_name=translated_filename,
        )

    except Exception as exc:
        app.logger.exception("Erro ao traduzir arquivo")
        msg = str(exc)

        if (
            "not installed" in msg.lower()
            or "no translation" in msg.lower()
            or "translation" in msg.lower()
        ):
            msg += (
                "\n\nVerifique se o modelo offline para esse par de "
                "idiomas foi instalado."
            )

        return jsonify(error=msg), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

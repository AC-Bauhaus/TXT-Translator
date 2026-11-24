
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
import torch
import transformers
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
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
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

TRANSLATION_MODES = {
    "fast": {
        "name": "Rápido",
        "chunk_size": 8000,
        "beam_size": 1,
        "description": "Prioriza a velocidade de processamento.",
        "engine": "argos",
    },

    "balanced": {
        "name": "Equilibrado",
        "chunk_size": 1800,
        "beam_size": 2,
        "description": "Usa NLLB-200 600M buscando equilíbrio entre velocidade e qualidade.",
        "engine": "nllb-600m",
    },

    "quality": {
        "name": "Melhor qualidade",
        "chunk_size": 1200,
        "beam_size": 4,
        "description": "Usa NLLB-200 1.3B priorizando a qualidade da tradução.",
        "engine": "nllb-1.3b",
    },
}

# As tarefas são compartilhadas entre as rotas HTTP e as threads de tradução.
translation_jobs = {}
translation_jobs_lock = threading.Lock()

# Guarda qual beam_size foi usado por último em cada par de idiomas, para
# saber quando é preciso limpar o cache interno do Argos Translate.
_translation_cache_state = {}
_translation_cache_lock = threading.Lock()

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

NLLB_LANGUAGES = {
    "en": "eng_Latn",
    "pt": "por_Latn",
    "pb": "por_Latn",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "ru": "rus_Cyrl",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "tr": "tur_Latn",
    "uk": "ukr_Cyrl",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
    "hu": "hun_Latn",
    "id": "ind_Latn",
    "ms": "zsm_Latn",
    "sv": "swe_Latn",
    "fi": "fin_Latn",
    "el": "ell_Grek",
    "he": "heb_Hebr",
    "cs": "ces_Latn",
    "da": "dan_Latn",
    "fa": "pes_Arab",
    "ga": "gle_Latn",
    "ro": "ron_Latn",
    "bg": "bul_Cyrl",
    "hr": "hrv_Latn",
    "sk": "slk_Latn",
    "sl": "slv_Latn",
}

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

def _clear_translation_cache(translation):
    """Limpa o cache interno do Argos Translate para essa tradução.

    O Argos guarda esse cache por texto (para repetir traduções
    idênticas mais rápido), mas não leva o beam_size em conta. Sem
    isso, ao trocar de modo, um trecho repetido voltaria com o
    resultado antigo em vez de usar o beam_size novo.
    """
    cache = getattr(translation, "cache", None)

    if isinstance(cache, dict):
        cache.clear()

    for attribute in ("t1", "t2", "underlying"):
        nested = getattr(translation, attribute, None)

        if nested is not None:
            _clear_translation_cache(nested)

@lru_cache(maxsize=2)
def get_nllb_model(model_name):
    if model_name == "nllb-600m":
        model_id = "facebook/nllb-200-distilled-600M"
    elif model_name == "nllb-1.3b":
        model_id = "facebook/nllb-200-distilled-1.3B"
    else:
        raise ValueError(f"Modelo NLLB desconhecido: {model_name}")

    model_path = resource_path(f"models/{model_name}")

    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        local_files_only=True,
    )

    model = AutoModelForSeq2SeqLM.from_pretrained(
        model_path,
        local_files_only=True,
    )

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    model = model.to(device)
    model.eval()

    return tokenizer, model, device


def adapt_to_brazilian_portuguese(text):
    """
    Adapta uma tradução em português produzida pelo NLLB
    para o padrão brasileiro (PT-BR).

    O NLLB usa por_Latn para português e não possui um código
    separado de pt-BR. Esta etapa normaliza:
      - vocabulário PT-PT;
      - ortografia europeia;
      - construções verbais de 2ª pessoa;
      - algumas construções e expressões muito comuns em PT-PT.

    A ordem das regras é importante: expressões completas são
    corrigidas antes de palavras isoladas.
    """
    import re

    def preserve_case(match, replacement):
        original = match.group(0)

        if original.isupper():
            return replacement.upper()

        if original[:1].isupper():
            return replacement[:1].upper() + replacement[1:]

        return replacement

    replacements = [
        # ----------------------------------------------------------
        # Construções com TU: transformar para o tratamento mais
        # comum do português brasileiro e ajustar a conjugação.
        # ----------------------------------------------------------
        (r"\btu\s+estás\b", "você está"),
        (r"\btu\s+estais\b", "vocês estão"),
        (r"\btu\s+tens\b", "você tem"),
        (r"\btu\s+tendes\b", "vocês têm"),
        (r"\btu\s+podes\b", "você pode"),
        (r"\btu\s+podeis\b", "vocês podem"),
        (r"\btu\s+queres\b", "você quer"),
        (r"\btu\s+quereis\b", "vocês querem"),
        (r"\btu\s+vais\b", "você vai"),
        (r"\btu\s+ides\b", "vocês vão"),
        (r"\btu\s+sabes\b", "você sabe"),
        (r"\btu\s+sabeis\b", "vocês sabem"),
        (r"\btu\s+fazes\b", "você faz"),
        (r"\btu\s+fazeis\b", "vocês fazem"),
        (r"\btu\s+dizes\b", "você diz"),
        (r"\btu\s+dizeis\b", "vocês dizem"),
        (r"\btu\s+vens\b", "você vem"),
        (r"\btu\s+vindes\b", "vocês vêm"),
        (r"\btu\s+deves\b", "você deve"),
        (r"\btu\s+deveis\b", "vocês devem"),
        (r"\btu\s+consegues\b", "você consegue"),
        (r"\btu\s+conseguis\b", "vocês conseguem"),
        (r"\btu\s+precisas\b", "você precisa"),
        (r"\btu\s+precisais\b", "vocês precisam"),
        (r"\btu\s+deixas\b", "você deixa"),
        (r"\btu\s+deixais\b", "vocês deixam"),
        (r"\btu\s+achas\b", "você acha"),
        (r"\btu\s+achais\b", "vocês acham"),
        (r"\btu\s+pensas\b", "você pensa"),
        (r"\btu\s+pensais\b", "vocês pensam"),
        (r"\btu\s+querias\b", "você queria"),
        (r"\btu\s+queríeis\b", "vocês queriam"),
        (r"\btu\s+tinhas\b", "você tinha"),
        (r"\btu\s+tínheis\b", "vocês tinham"),
        (r"\btu\s+podias\b", "você podia"),
        (r"\btu\s+podíeis\b", "vocês podiam"),
        (r"\btu\s+devias\b", "você devia"),
        (r"\btu\s+devíeis\b", "vocês deviam"),
        (r"\btu\s+foste\b", "você foi"),
        (r"\btu\s+fizeste\b", "você fez"),
        (r"\btu\s+disse\b", "você disse"),
        (r"\btu\s+viste\b", "você viu"),
        (r"\btu\s+puseste\b", "você colocou"),
        (r"\btu\s+quiseste\b", "você quis"),

        # Pronomes de tratamento.
        (r"\bvosso\b", "seu"),
        (r"\bvossa\b", "sua"),
        (r"\bvossos\b", "seus"),
        (r"\bvossas\b", "suas"),
        (r"\bconnosco\b", "conosco"),
        (r"\bconvosco\b", "com vocês"),

        # ----------------------------------------------------------
        # Expressões e vocabulário fortemente característicos de PT-PT
        # ----------------------------------------------------------
        (r"\bpequeno[- ]almoço\b", "café da manhã"),
        (r"\bcasa de banho\b", "banheiro"),
        (r"\bquarto de banho\b", "banheiro"),
        (r"\bpalavras[- ]passe\b", "senhas"),
        (r"\bpalavra[- ]passe\b", "senha"),
        (r"\bcódigo postal\b", "CEP"),
        (r"\bcorreio electrónico\b", "e-mail"),
        (r"\bcorreio eletrónico\b", "e-mail"),
        (r"\bcorreio electrónico\b", "e-mail"),
        (r"\bbase de dados\b", "banco de dados"),
        (r"\bbases de dados\b", "bancos de dados"),
        (r"\bde seguida\b", "em seguida"),
        (r"\bde momento\b", "no momento"),
        (r"\bà partida\b", "a princípio"),
        (r"\bpor forma a\b", "para"),
        (r"\bde modo a\b", "para"),
        (r"\bde maneira a\b", "para"),
        (r"\bter em conta\b", "levar em conta"),
        (r"\bdar conta\b", "perceber"),
        (r"\bdar-se conta\b", "perceber"),
        (r"\bdar-se por conta\b", "perceber"),
        (r"\bem termos de\b", "em relação a"),

        # ----------------------------------------------------------
        # Construções que precisam de ajuste de artigo após a
        # conversão do vocabulário.
        # ----------------------------------------------------------
        (r"\bno ecrã\b", "na tela"),
        (r"\bno ecrãs\b", "nas telas"),
        (r"\bà aplicação\b", "ao aplicativo"),
        (r"\bà aplicações\b", "aos aplicativos"),
        (r"\ba aplicação\b", "o aplicativo"),
        (r"\bas aplicações\b", "os aplicativos"),
        (r"\buma aplicação\b", "um aplicativo"),
        (r"\buma aplicações\b", "uns aplicativos"),
        (r"\bna aplicação\b", "no aplicativo"),
        (r"\bnas aplicações\b", "nos aplicativos"),
        (r"\bda aplicação\b", "do aplicativo"),
        (r"\bdas aplicações\b", "dos aplicativos"),
        (r"\besta aplicação\b", "este aplicativo"),
        (r"\bestas aplicações\b", "estes aplicativos"),
        (r"\bessa aplicação\b", "esse aplicativo"),
        (r"\bessas aplicações\b", "esses aplicativos"),

        (r"\bacessar ao\b", "acessar o"),

        # Verbos/expressões frequentes que permanecem em PT-PT.
        (r"\bapanhar\b", "pegar"),
        (r"\bapanha\b", "pega"),
        (r"\bapanhei\b", "peguei"),
        (r"\bapanhou\b", "pegou"),
        (r"\bapanhará\b", "pegará"),
        (r"\bter de\b", "ter que"),
        (r"\btens de\b", "tem que"),
        (r"\btem de\b", "tem que"),
        (r"\btêm de\b", "têm que"),
        (r"\bdeverá de\b", "deverá"),
        (r"\bdeveriam de\b", "deveriam"),

        # ----------------------------------------------------------
        # Informática / tecnologia
        # ----------------------------------------------------------
        (r"\bficheiros\b", "arquivos"),
        (r"\bficheiro\b", "arquivo"),
        (r"\butilizadores\b", "usuários"),
        (r"\butilizadoras\b", "usuárias"),
        (r"\butilizador\b", "usuário"),
        (r"\butilizadora\b", "usuária"),
        (r"\becrãs\b", "telas"),
        (r"\becrã\b", "tela"),
        (r"\btelemóveis\b", "celulares"),
        (r"\btelemóvel\b", "celular"),
        (r"\bcomputadores portáteis\b", "notebooks"),
        (r"\bcomputador portátil\b", "notebook"),
        (r"\baplicações\b", "aplicativos"),
        (r"\baplicação\b", "aplicativo"),
        (r"\bprogramas informáticos\b", "programas de computador"),
        (r"\bprograma informático\b", "programa de computador"),
        (r"\bpágina web\b", "página da web"),
        (r"\bpáginas web\b", "páginas da web"),
        (r"\bpalavra-passe\b", "senha"),
        (r"\bpalavras-passe\b", "senhas"),

        # ----------------------------------------------------------
        # Transporte
        # ----------------------------------------------------------
        (r"\bautocarros\b", "ônibus"),
        (r"\bautocarro\b", "ônibus"),
        (r"\bcomboios\b", "trens"),
        (r"\bcomboio\b", "trem"),
        (r"\bmetro\b", "metrô"),
        (r"\bparagem de autocarro\b", "ponto de ônibus"),
        (r"\bparagem\b", "parada"),
        (r"\bcondutores\b", "motoristas"),
        (r"\bcondutor\b", "motorista"),

        # ----------------------------------------------------------
        # Alimentação / casa / cotidiano
        # ----------------------------------------------------------
        (r"\bsumo de laranja\b", "suco de laranja"),
        (r"\bsumos\b", "sucos"),
        (r"\bsumo\b", "suco"),
        (r"\bgelados\b", "sorvetes"),
        (r"\bgelado\b", "sorvete"),
        (r"\bfiambre\b", "presunto"),
        (r"\bfrigoríficos\b", "geladeiras"),
        (r"\bfrigorífico\b", "geladeira"),
        (r"\bpeúgas\b", "meias"),
        (r"\bcuecas\b", "cuecas"),
        (r"\bcamisolas\b", "blusas"),
        (r"\bcamisola\b", "blusa"),
        (r"\bcalções\b", "shorts"),
        (r"\bautocolantes\b", "adesivos"),
        (r"\bautocolante\b", "adesivo"),

        # ----------------------------------------------------------
        # Trabalho / educação / serviços
        # ----------------------------------------------------------
        (r"\bempregado de mesa\b", "garçom"),
        (r"\bempregada de mesa\b", "garçonete"),
        (r"\bordenados\b", "salários"),
        (r"\bordenado\b", "salário"),
        (r"\bdespedimentos\b", "demissões"),
        (r"\bdespedimento\b", "demissão"),
        (r"\bdespedido\b", "demitido"),
        (r"\bdespedida\b", "demitida"),
        (r"\bpropinas\b", "mensalidades"),
        (r"\bpropina\b", "mensalidade"),
        (r"\bensino secundário\b", "ensino médio"),
        (r"\bparque de estacionamento\b", "estacionamento"),
        (r"\besquadra de polícia\b", "delegacia de polícia"),
        (r"\besquadra\b", "delegacia"),

        # ----------------------------------------------------------
        # Vocabulário coloquial
        # ----------------------------------------------------------
        (r"\bfixe\b", "legal"),
        (r"\bfixolas\b", "legal"),
        (r"\bgiro\b", "legal"),
        (r"\bgira\b", "legal"),
        (r"\bgiros\b", "legais"),
        (r"\bgiras\b", "legais"),
        (r"\bmiúdos\b", "garotos"),
        (r"\bmiúdas\b", "garotas"),
        (r"\bmiúdo\b", "garoto"),
        (r"\bmiúda\b", "garota"),
        (r"\braparigas\b", "meninas"),
        (r"\brapariga\b", "menina"),
        (r"\bputos\b", "garotos"),
        (r"\bputo\b", "garoto"),
        (r"\bputas\b", "garotas"),
        (r"\bputo\b", "garoto"),

        # ----------------------------------------------------------
        # Verbos e formas lexicais
        # ----------------------------------------------------------
        (r"\butilizámos\b", "usamos"),
        (r"\butilizámos\b", "usamos"),
        (r"\butilizarão\b", "usarão"),
        (r"\butilizará\b", "usará"),
        (r"\butilizaria\b", "usaria"),
        (r"\butilizavam\b", "usavam"),
        (r"\butilizava\b", "usava"),
        (r"\butilizado\b", "usado"),
        (r"\butilizada\b", "usada"),
        (r"\butilizados\b", "usados"),
        (r"\butilizadas\b", "usadas"),
        (r"\butilizam\b", "usam"),
        (r"\butiliza\b", "usa"),
        (r"\butilizar\b", "usar"),

        (r"\baceder\b", "acessar"),
        (r"\bacedido\b", "acessado"),
        (r"\bacedida\b", "acessada"),
        (r"\bacesso\b", "acesso"),
        (r"\bseleccionar\b", "selecionar"),
        (r"\bseleccionado\b", "selecionado"),
        (r"\bseleccionada\b", "selecionada"),
        (r"\bseleccionados\b", "selecionados"),
        (r"\bseleccionadas\b", "selecionadas"),
        (r"\bselecciona\b", "seleciona"),
        (r"\bseleccionar\b", "selecionar"),

        (r"\bactualizações\b", "atualizações"),
        (r"\bactualização\b", "atualização"),
        (r"\bactualizado\b", "atualizado"),
        (r"\bactualizada\b", "atualizada"),
        (r"\bactualizar\b", "atualizar"),
        (r"\bactualmente\b", "atualmente"),
        (r"\bactual\b", "atual"),

        (r"\bactividades\b", "atividades"),
        (r"\bactividade\b", "atividade"),
        (r"\bactivar\b", "ativar"),
        (r"\bactiva\b", "ativa"),
        (r"\bactivado\b", "ativado"),
        (r"\bactivada\b", "ativada"),
        (r"\bactivação\b", "ativação"),

        (r"\bdesactivar\b", "desativar"),
        (r"\bdesactiva\b", "desativa"),
        (r"\bdesactivado\b", "desativado"),
        (r"\bdesactivada\b", "desativada"),

        (r"\boptimizações\b", "otimizações"),
        (r"\boptimização\b", "otimização"),
        (r"\boptimizar\b", "otimizar"),
        (r"\bóptimas\b", "ótimas"),
        (r"\bóptimos\b", "ótimos"),
        (r"\bóptima\b", "ótima"),
        (r"\bóptimo\b", "ótimo"),

        (r"\bprojectos\b", "projetos"),
        (r"\bprojecto\b", "projeto"),
        (r"\bprojectar\b", "projetar"),

        (r"\bobjectivos\b", "objetivos"),
        (r"\bobjectivo\b", "objetivo"),
        (r"\bobjectivas\b", "objetivas"),
        (r"\bobjectiva\b", "objetiva"),

        # ----------------------------------------------------------
        # Ortografia europeia: c, ct, cc etc.
        # ----------------------------------------------------------
        (r"\bactividade\b", "atividade"),
        (r"\bactividades\b", "atividades"),
        (r"\bacto\b", "ato"),
        (r"\bactos\b", "atos"),
        (r"\bafecto\b", "afeto"),
        (r"\bafectos\b", "afetos"),
        (r"\bafectar\b", "afetar"),
        (r"\bafectado\b", "afetado"),
        (r"\bafectada\b", "afetada"),
        (r"\bcolectivo\b", "coletivo"),
        (r"\bcolectiva\b", "coletiva"),
        (r"\bcolectivos\b", "coletivos"),
        (r"\bcolectivas\b", "coletivas"),
        (r"\bdirecto\b", "direto"),
        (r"\bdirecta\b", "direta"),
        (r"\bdirectamente\b", "diretamente"),
        (r"\bdirecção\b", "direção"),
        (r"\bdirecções\b", "direções"),
        (r"\binteracção\b", "interação"),
        (r"\binteracções\b", "interações"),
        (r"\bprotecção\b", "proteção"),
        (r"\bprotecções\b", "proteções"),
        (r"\bselecção\b", "seleção"),
        (r"\bselecções\b", "seleções"),
        (r"\bconcepção\b", "concepção"),
        (r"\bpercepção\b", "percepção"),
        (r"\brecepção\b", "recepção"),
        (r"\bexcepção\b", "exceção"),
        (r"\bexcepções\b", "exceções"),
        (r"\bcontactos\b", "contatos"),
        (r"\bcontacto\b", "contato"),
        (r"\bfactos\b", "fatos"),
        (r"\bfacto\b", "fato"),
        (r"\bcarácter\b", "caráter"),
        (r"\bcarácter\b", "caráter"),

        # ----------------------------------------------------------
        # Formas de 2ª pessoa que podem aparecer sem "tu".
        # Elas são tratadas somente quando a forma é claramente
        # uma conjugação de 2ª pessoa singular/plural.
        # ----------------------------------------------------------
        (r"\bestás\b", "está"),
        (r"\bestais\b", "estão"),
        (r"\btens\b", "tem"),
        (r"\btendes\b", "têm"),
        (r"\bpodes\b", "pode"),
        (r"\bpodeis\b", "podem"),
        (r"\bqueres\b", "quer"),
        (r"\bquereis\b", "querem"),
        (r"\bvais\b", "vai"),
        (r"\bides\b", "vão"),
        (r"\bsabes\b", "sabe"),
        (r"\bsabeis\b", "sabem"),
        (r"\bfazes\b", "faz"),
        (r"\bfazeis\b", "fazem"),
        (r"\bdizes\b", "diz"),
        (r"\bdizeis\b", "dizem"),
        (r"\bvês\b", "vê"),
        (r"\bvedes\b", "veem"),
        (r"\bvens\b", "vem"),
        (r"\bvindes\b", "vêm"),
        (r"\bdeves\b", "deve"),
        (r"\bdeveis\b", "devem"),
        (r"\bconsegues\b", "consegue"),
        (r"\bconseguis\b", "conseguem"),
        (r"\bprecisas\b", "precisa"),
        (r"\bprecisais\b", "precisam"),
        (r"\bdeixas\b", "deixa"),
        (r"\bdeixais\b", "deixam"),
        (r"\bachas\b", "acha"),
        (r"\bachais\b", "acham"),
        (r"\bpensas\b", "pensa"),
        (r"\bpensais\b", "pensam"),

        # ----------------------------------------------------------
        # Palavras com grafia/acentuação diferente
        # ----------------------------------------------------------
        (r"\bperíodo\b", "período"),
        (r"\bvídeo\b", "vídeo"),
        (r"\bautocarro\b", "ônibus"),
        (r"\btelemóvel\b", "celular"),
        (r"\bficheiro\b", "arquivo"),
        (r"\becrã\b", "tela"),
    ]

    result = text

    for pattern, replacement in replacements:
        result = re.sub(
            pattern,
            lambda match, replacement=replacement:
                preserve_case(match, replacement),
            result,
            flags=re.IGNORECASE | re.UNICODE,
        )

    # Limpeza de espaçamento criada por algumas substituições.
    result = re.sub(r"[ \t]+([,.!?;:])", r"\1", result)
    result = re.sub(r" {2,}", " ", result)

    return result


def translate_chunk_nllb(text, source, target, mode="balanced"):
    mode_settings = TRANSLATION_MODES.get(
        mode,
        TRANSLATION_MODES["balanced"],
    )

    model_name = mode_settings["engine"]

    if source not in NLLB_LANGUAGES:
        raise RuntimeError(
            f"O idioma de origem '{source}' não é suportado pelo NLLB."
        )

    if target not in NLLB_LANGUAGES:
        raise RuntimeError(
            f"O idioma de destino '{target}' não é suportado pelo NLLB."
        )

    tokenizer, model, device = get_nllb_model(model_name)

    source_lang = NLLB_LANGUAGES[source]
    target_lang = NLLB_LANGUAGES[target]

    tokenizer.src_lang = source_lang

    # O NLLB possui limite de entrada de 512 tokens.
    # 450 deixa margem para tokens especiais sem truncar conteúdo.
    max_input_tokens = 450

    def token_count(value):
        return len(
            tokenizer(
                value,
                add_special_tokens=True,
                truncation=False,
            )["input_ids"]
        )

    def split_text_by_tokens(value):
        """Divide o texto sem ultrapassar o limite seguro do NLLB."""
        if not value.strip():
            return [value]

        parts = []
        paragraphs = re.split(r"(\n+)", value)

        for paragraph in paragraphs:
            if not paragraph or paragraph.isspace():
                parts.append(paragraph)
                continue

            sentences = re.split(
                r"(?<=[.!?。！？])\s+",
                paragraph,
            )

            current = ""

            for sentence in sentences:
                sentence = sentence.strip()

                if not sentence:
                    continue

                candidate = (
                    f"{current} {sentence}".strip()
                    if current
                    else sentence
                )

                if token_count(candidate) <= max_input_tokens:
                    current = candidate
                    continue

                if current:
                    parts.append(current)
                    current = ""

                if token_count(sentence) <= max_input_tokens:
                    current = sentence
                    continue

                # Frase muito grande: divide por palavras.
                words = sentence.split()
                word_buffer = ""

                for word in words:
                    candidate = (
                        f"{word_buffer} {word}".strip()
                        if word_buffer
                        else word
                    )

                    if token_count(candidate) <= max_input_tokens:
                        word_buffer = candidate
                    else:
                        if word_buffer:
                            parts.append(word_buffer)

                        # Palavra isolada extremamente longa.
                        if token_count(word) > max_input_tokens:
                            # Divide por caracteres como último recurso.
                            char_buffer = ""
                            for char in word:
                                char_candidate = char_buffer + char

                                if token_count(char_candidate) <= max_input_tokens:
                                    char_buffer = char_candidate
                                else:
                                    if char_buffer:
                                        parts.append(char_buffer)
                                    char_buffer = char

                            word_buffer = char_buffer
                        else:
                            word_buffer = word

                if word_buffer:
                    current = word_buffer

            if current:
                parts.append(current)

        return parts

    text_parts = split_text_by_tokens(text)
    translated_parts = []

    forced_bos_token_id = tokenizer.convert_tokens_to_ids(
        target_lang
    )

    for part in text_parts:
        if not part or part.isspace():
            translated_parts.append(part)
            continue

        encoded = tokenizer(
            part,
            return_tensors="pt",
            truncation=False,
        )

        encoded = {
            key: value.to(device)
            for key, value in encoded.items()
        }

        with torch.inference_mode():
            generated_tokens = model.generate(
                **encoded,
                forced_bos_token_id=forced_bos_token_id,
                num_beams=mode_settings["beam_size"],
                max_length=512,
            )

        translated_parts.append(
            tokenizer.batch_decode(
                generated_tokens,
                skip_special_tokens=True,
            )[0]
        )

    # Junta as partes antes da adaptação para PT-BR. Isso evita que
    # uma regra dependa da fronteira artificial de um chunk.
    translated_text = "".join(translated_parts)

    if target == "pb":
        translated_text = adapt_to_brazilian_portuguese(
            translated_text
        )

    return translated_text


def translate_chunk(text, source, target, mode="balanced"):
    try:
        mode_settings = TRANSLATION_MODES.get(
            mode,
            TRANSLATION_MODES["balanced"],
        )

        if mode_settings["engine"].startswith("nllb"):
            return translate_chunk_nllb(
                text,
                source,
                target,
                mode,
            )

        beam_size = mode_settings["beam_size"]

        # Ajusta a precisão da busca do tradutor conforme o modo escolhido.
        argos_settings.beam_size = beam_size

        translation = get_translation_model(source, target)

        # Se o modo mudou para esse par de idiomas desde a última vez,
        # limpa o cache interno antes de traduzir — senão um trecho
        # repetido voltaria com o resultado do beam_size anterior.
        cache_key = (source, target)

        with _translation_cache_lock:
            if _translation_cache_state.get(cache_key) != beam_size:
                _clear_translation_cache(translation)
                _translation_cache_state[cache_key] = beam_size

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


@lru_cache(maxsize=256)
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
                translate_chunk(unit, source, target, mode)
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

def join_pdf_lines(text):
    """Junta as linhas de um bloco de PDF para traduzir a frase inteira."""
    # remove hifenização de fim de linha (ex.: "hy-\nphenated" -> "hyphenated")
    text = re.sub(r"(\w)-\n([a-zà-ÿ])", r"\1\2", text)
    # troca as demais quebras de linha por espaço
    return re.sub(r"\s*\n\s*", " ", text).strip()

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
        import pymupdf

    except ImportError as exc:
        raise RuntimeError(
            "A biblioteca PyMuPDF não está instalada."
        ) from exc

    document = pymupdf.open(stream=data, filetype="pdf")

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

                rect = pymupdf.Rect(block[:4])

                if rect.is_empty or rect.is_infinite:
                    continue

                weight = max(1, len(original))

                valid_blocks.append((rect, block[4], weight))
                total_weight += weight

                pages_with_blocks.append((page, valid_blocks))

        if total_weight == 0:
            raise ValueError(
                "Este PDF não tem texto selecionável (provavelmente é "
                "escaneado). Faça OCR antes de traduzir."
            )

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
                    join_pdf_lines(original_text),
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

def decode_txt_bytes(data):
    """Lê o TXT em UTF-8, UTF-16 (com BOM), Windows-1252 ou Latin-1."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")

    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    return data.decode("latin-1")

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
            original = decode_txt_bytes(data)

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
            "não existe modelo" in message.lower()
            or "no translation" in message.lower()
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

    source = request.form.get("source", "en")
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
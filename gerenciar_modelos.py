"""Manage Argos Translate models. Network is used only when explicitly downloading a model."""
import argparse
import os
import sys

LANG_NAMES = {"en":"Inglês", "pt":"Português", "pb":"Português (Brasil)", "es":"Espanhol", "fr":"Francês", "de":"Alemão", "it":"Italiano", "ja":"Japonês", "ko":"Coreano", "zh":"Chinês", "ru":"Russo", "nl":"Holandês", "pl":"Polonês", "tr":"Turco", "uk":"Ucraniano", "ar":"Árabe", "az":"Azerbaijano", "eu":"Basco", "ca":"Catalão", "cs":"Tcheco", "da":"Dinamarquês", "eo":"Esperanto", "fa":"Persa", "fi":"Finlandês", "gl":"Galego", "ga":"Irlandês", "el":"Grego", "he":"Hebraico", "hi":"Hindi", "hu":"Húngaro", "id":"Indonésio", "ky":"Quirguiz", "ms":"Malaio", "sv":"Sueco", "sw":"Suaíli", "ur":"Urdu"}

def main():
    parser = argparse.ArgumentParser(description="Gerenciador de modelos de tradução offline do TXT Tradutor")
    parser.add_argument("--list", action="store_true", help="listar idiomas/modelos instalados")
    parser.add_argument("--download", nargs=2, metavar=("ORIGEM", "DESTINO"), help="baixar e instalar modelo uma única vez (requer internet)")
    parser.add_argument("--install", metavar="ARQUIVO.ARGOSMODEL", help="instalar um modelo já baixado, sem internet")
    args = parser.parse_args()
    try:
        import argostranslate.package as package
        import argostranslate.translate as translate
    except ImportError:
        print("Dependência ausente. Execute: python -m pip install -r requirements.txt")
        return 1
    if args.list:
        langs = translate.get_installed_languages()
        print("Idiomas instalados:")
        for lang in langs:
            print(f"  {lang.code}: {LANG_NAMES.get(lang.code, lang.name)}")
        print("\nModelos disponíveis dependem dos idiomas e pares instalados.")
        return 0
    if args.install:
        if not os.path.isfile(args.install):
            print("Arquivo de modelo não encontrado:", args.install)
            return 2
        package.install_from_path(args.install)
        print("Modelo instalado localmente. Nenhuma conexão foi usada para essa instalação.")
        return 0
    if args.download:
        source, target = args.download
        print(f"Consultando catálogo para {source} -> {target}; isso requer internet apenas agora...")
        package.update_package_index()
        candidates = [p for p in package.get_available_packages() if p.from_code == source and p.to_code == target]
        if not candidates:
            print(f"Não foi encontrado modelo direto {source} -> {target} no catálogo.")
            return 3
        chosen = candidates[0]
        path = chosen.download()
        package.install_from_path(path)
        print("Modelo instalado. A tradução pode ser feita offline neste computador.")
        return 0
    parser.print_help()
    return 0

if __name__ == "__main__":
    sys.exit(main())

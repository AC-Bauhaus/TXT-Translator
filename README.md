# TXT Translator — Web Local

Esta versão transforma o projeto em uma **aplicação web local**: a interface roda no navegador, enquanto o motor de tradução continua no próprio computador.

## O que mudou

- Removido o `pywebview` e toda a camada de janela nativa.
- Removido o PyInstaller e dependências que não eram usadas pelo projeto atual.
- Mantido o backend Python/Flask local.
- Mantido o Argos Translate e os modelos offline no computador.
- Mantido processamento de TXT e PDF local.
- Mantidos palavras protegidas, dicionário personalizado, modos de tradução e progresso.
- Download do resultado feito diretamente pelo navegador.
- Adicionado cache de arquivos estáticos com Service Worker para reduzir acessos repetidos.
- O servidor fica preso em `127.0.0.1` por padrão, portanto o texto não é publicado na rede.
- Dependências reduzidas para instalar mais rápido e ocupar menos espaço.

## Privacidade

O fluxo normal de tradução não envia o conteúdo dos seus arquivos para serviços externos. O navegador conversa apenas com o servidor local em `127.0.0.1`.

A única operação que usa internet é o download inicial dos modelos Argos quando você escolhe instalar um modelo pelo painel. Depois de instalado, esse modelo pode ser usado offline.

## Linux / Arch / Garuda

```bash
sudo pacman -S --needed python python-pip python-virtualenv
cd TXT-Translator-web
./iniciar_linux.sh
```

O script cria o ambiente virtual, instala somente as dependências necessárias e abre o TXT Translator no navegador padrão.

Também é possível iniciar manualmente:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python start_web.py
```

## Windows 11

1. Instale **Python 3.12 (64-bit)** e marque **Add Python to PATH** durante a instalação. Python 3.11 também é aceito. Evite Python 3.15: algumas dependências, como PyYAML, podem tentar compilar código C/C++ nessa versão.
2. Extraia o ZIP para uma pasta normal (por exemplo, Documentos).
3. Execute `iniciar_windows.bat`. Na primeira execução, o script cria `.venv` e instala as dependências.
4. Acesse `http://127.0.0.1:5000/` no navegador. Mantenha a janela do CMD aberta enquanto usar o tradutor. O inicializador seleciona Python 3.12 (ou 3.11), recria automaticamente um `.venv` incompatível e instala PyYAML usando wheel binário.

Se ocorrer um erro, o CMD ficará aberto. Copie a mensagem exibida para identificar a causa. Se a instalação das dependências falhar, execute o BAT novamente: ele tentará concluir a instalação.

Para baixar um modelo offline (exemplo inglês → português), abra o CMD na pasta do projeto e execute:

```bat
.venv\Scripts\python.exe gerenciar_modelos.py --download en pt
```

Para listar os modelos instalados:

```bat
.venv\Scripts\python.exe gerenciar_modelos.py --list
```

## Uso

1. Abra o TXT Translator no navegador.
2. Selecione TXT ou PDF.
3. Escolha origem e destino.
4. Escolha o modo de tradução.
5. Clique em **Traduzir arquivo**.
6. Baixe o resultado pelo próprio navegador.

## Modelos offline

Exemplo inglês → português:

```bash
.venv/bin/python gerenciar_modelos.py --download en pt
```

Português → inglês:

```bash
.venv/bin/python gerenciar_modelos.py --download pt en
```

Listar modelos/idiomas instalados:

```bash
.venv/bin/python gerenciar_modelos.py --list
```

Instalar um `.argosmodel` já baixado, sem internet:

```bash
.venv/bin/python gerenciar_modelos.py --install /caminho/modelo.argosmodel
```

## Funcionamento local

Por padrão:

- Interface: `http://127.0.0.1:5000/`
- Backend: Flask no mesmo endereço
- Tradução: Argos Translate local
- Preferências: arquivo local no diretório de configuração do usuário
- Arquivos enviados: ficam em memória durante a tarefa e não são enviados para terceiros

Para mudar a porta:

```bash
TXT_TRANSLATOR_PORT=8080 python start_web.py
```

Para disponibilizar na rede local, é possível alterar `TXT_TRANSLATOR_HOST`, mas isso **não é recomendado** se você quer manter os arquivos restritos ao próprio computador.

## Estrutura

```text
TXT-Translator-web/
├── app.py
├── start_web.py
├── gerenciar_modelos.py
├── requirements.txt
├── iniciar_linux.sh
├── iniciar_windows.bat
├── templates/
│   └── index.html
└── static/
    ├── scripts.js
    ├── styles.css
    ├── manifest.webmanifest
    └── sw.js
```
